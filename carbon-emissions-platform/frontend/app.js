/* =========================================================================
 * Central Steel Plant - ESG Emissions Dashboard (vanilla JS, no build step)
 * Talks to the FastAPI backend at the same origin via relative /api/... URLs.
 * Charts via Chart.js (CDN global `Chart`).
 * ========================================================================= */
"use strict";

// --------------------------------------------------------------------------
// Small helpers
// --------------------------------------------------------------------------
const $ = (id) => document.getElementById(id);

/** Fetch JSON with explicit error surfacing. */
async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  let body = null;
  const text = await res.text();
  if (text) {
    try { body = JSON.parse(text); } catch { body = text; }
  }
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    if (body && body.detail) {
      msg = typeof body.detail === "string"
        ? body.detail
        : JSON.stringify(body.detail);
    } else if (typeof body === "string" && body) {
      msg = body;
    }
    throw new Error(msg);
  }
  return body;
}

/** Compact, human-friendly number formatting for big kgCO2e values. */
function fmtCompact(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e9) return (n / 1e9).toFixed(2) + "B";
  if (abs >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (abs >= 1e3) return (n / 1e3).toFixed(2) + "K";
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

/** Full grouped number (e.g. 35,927,330,587). */
function fmtFull(n, digits = 0) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return Number(n).toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  });
}

function fmtPct(p) {
  if (p === null || p === undefined || Number.isNaN(p)) return "—";
  const sign = p > 0 ? "+" : "";
  return `${sign}${p.toFixed(2)}%`;
}

function escapeHtml(s) {
  if (s === null || s === undefined) return "";
  return String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function todayISO() { return new Date().toISOString().slice(0, 10); }

// --------------------------------------------------------------------------
// Chart-state (loading / error / empty) helper
// --------------------------------------------------------------------------
function setChartState(id, mode, message) {
  const el = $(id);
  if (!el) return;
  if (mode === "hide") {
    el.classList.remove("show", "err");
    el.innerHTML = "";
    return;
  }
  el.classList.add("show");
  el.classList.toggle("err", mode === "error");
  if (mode === "loading") {
    el.innerHTML = `<div><div class="spinner"></div>Loading…</div>`;
  } else {
    el.innerHTML = `<div>${escapeHtml(message || "")}</div>`;
  }
}

// --------------------------------------------------------------------------
// Activity catalogue (drives the record form dropdown). Mirrors seeded
// factors; also fetched live from /api/factors to stay in sync.
// --------------------------------------------------------------------------
const FALLBACK_ACTIVITIES = {
  1: [
    { activity: "Diesel", unit: "KL", category: "Pellet Plant" },
    { activity: "Natural Gas", unit: "kNm3", category: "Pellet Plant" },
    { activity: "Anthracite Coal", unit: "tonne", category: "Pellet Plant" },
    { activity: "Bituminous Coal", unit: "tonne", category: "Pellet Plant" },
    { activity: "Petroleum Coke", unit: "tonne", category: "Pellet Plant" },
    { activity: "Fuel Oil", unit: "KL", category: "Power Plant" },
    { activity: "LPG", unit: "tonne", category: "Rolling Mill" },
    { activity: "Kerosene", unit: "KL", category: "DRI" },
    { activity: "Limestone", unit: "tonne", category: "SMS" },
  ],
  2: [
    { activity: "Grid Electricity", unit: "kWh", category: "EAF" },
    { activity: "Open Access Power", unit: "kWh", category: "Rolling Mill" },
    { activity: "Captive Solar+Grid", unit: "kWh", category: "Pellet Plant" },
    { activity: "Imported Steam", unit: "GJ", category: "Utilities" },
    { activity: "Local Discom Power", unit: "kWh", category: "Admin Buildings" },
  ],
};

// Activity meta keyed by activity name -> {unit, category}; populated from
// /api/factors with the fallback as the baseline.
const ACTIVITY_META = {};
const ACTIVITIES_BY_SCOPE = { 1: [], 2: [] };

function seedActivityCatalogue(source) {
  ACTIVITIES_BY_SCOPE[1] = [];
  ACTIVITIES_BY_SCOPE[2] = [];
  for (const scope of [1, 2]) {
    const seen = new Set();
    for (const item of source[scope] || []) {
      if (seen.has(item.activity)) continue;
      seen.add(item.activity);
      ACTIVITIES_BY_SCOPE[scope].push(item.activity);
      ACTIVITY_META[item.activity] = { unit: item.unit, category: item.category, scope };
    }
  }
}

async function loadFactorCatalogue() {
  // Start with fallback so the form always works even if the call fails.
  seedActivityCatalogue(FALLBACK_ACTIVITIES);
  try {
    const factors = await api("/api/factors");
    const grouped = { 1: [], 2: [] };
    const seen = new Set();
    for (const f of factors) {
      const key = `${f.scope}|${f.activity}`;
      if (seen.has(key)) continue;
      seen.add(key);
      grouped[f.scope].push({ activity: f.activity, unit: f.unit, category: f.category });
    }
    if (grouped[1].length || grouped[2].length) {
      seedActivityCatalogue(grouped);
    }
  } catch (err) {
    console.warn("Falling back to built-in activity catalogue:", err.message);
  }
  populateActivityDropdown();
}

function populateActivityDropdown() {
  const scope = Number($("recScope").value);
  const sel = $("recActivity");
  sel.innerHTML = "";
  for (const act of ACTIVITIES_BY_SCOPE[scope] || []) {
    const opt = document.createElement("option");
    opt.value = act;
    opt.textContent = act;
    sel.appendChild(opt);
  }
  syncActivityDefaults();
}

function syncActivityDefaults() {
  const act = $("recActivity").value;
  const meta = ACTIVITY_META[act];
  if (meta) {
    $("recUnit").value = meta.unit || "";
    $("recCategory").value = meta.category || "";
  }
}

// --------------------------------------------------------------------------
// Chart registry (so we can destroy + rebuild on year change)
// --------------------------------------------------------------------------
const charts = { yoy: null, hotspot: null, trend: null };

const PALETTE = [
  "#15803d", "#22c55e", "#0d9488", "#65a30d", "#0891b2",
  "#84cc16", "#059669", "#10b981", "#14b8a6", "#4d7c0f",
  "#047857", "#34d399", "#a3e635", "#2dd4bf",
];
const SCOPE1_COLOR = "#0d9488"; // teal
const SCOPE2_COLOR = "#16a34a"; // green

function destroyChart(key) {
  if (charts[key]) { charts[key].destroy(); charts[key] = null; }
}

// --------------------------------------------------------------------------
// 1) Stacked bar - YoY emissions by scope
// --------------------------------------------------------------------------
async function renderYoY(year) {
  setChartState("yoyState", "loading");
  try {
    const data = await api(`/api/analytics/yoy?year=${year}`);
    destroyChart("yoy");
    const labels = [`${data.prev_year}`, `${data.year}`];
    const scope1 = [data.previous.scope1, data.current.scope1];
    const scope2 = [data.previous.scope2, data.current.scope2];

    if (data.current.total === 0 && data.previous.total === 0) {
      setChartState("yoyState", "empty", "No emissions data for these years.");
      return;
    }
    setChartState("yoyState", "hide");

    charts.yoy = new Chart($("yoyChart"), {
      type: "bar",
      data: {
        labels,
        datasets: [
          { label: "Scope 1", data: scope1, backgroundColor: SCOPE1_COLOR, stack: "e", borderRadius: 4 },
          { label: "Scope 2", data: scope2, backgroundColor: SCOPE2_COLOR, stack: "e", borderRadius: 4 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom" },
          tooltip: {
            callbacks: {
              label: (c) => `${c.dataset.label}: ${fmtFull(c.parsed.y)} kgCO₂e`,
              footer: (items) => {
                const t = items.reduce((s, i) => s + i.parsed.y, 0);
                return `Total: ${fmtFull(t)} kgCO₂e`;
              },
            },
          },
        },
        scales: {
          x: { stacked: true, grid: { display: false } },
          y: {
            stacked: true,
            ticks: { callback: (v) => fmtCompact(v) },
            title: { display: true, text: "kgCO₂e" },
          },
        },
      },
    });
  } catch (err) {
    setChartState("yoyState", "error", `Failed to load: ${err.message}`);
  }
}

// --------------------------------------------------------------------------
// 2) Donut - emission hotspot (% by source)
// --------------------------------------------------------------------------
async function renderHotspot(year) {
  setChartState("hotspotState", "loading");
  try {
    const items = await api(`/api/analytics/hotspot?year=${year}`);
    destroyChart("hotspot");
    if (!items.length) {
      setChartState("hotspotState", "empty", "No emission sources for this year.");
      return;
    }
    setChartState("hotspotState", "hide");

    const labels = items.map((i) => i.source);
    const values = items.map((i) => i.kgco2e);
    const pcts = items.map((i) => i.pct_of_total);

    charts.hotspot = new Chart($("hotspotChart"), {
      type: "doughnut",
      data: {
        labels,
        datasets: [{
          data: values,
          backgroundColor: labels.map((_, i) => PALETTE[i % PALETTE.length]),
          borderColor: "#fff",
          borderWidth: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "58%",
        plugins: {
          legend: {
            position: "right",
            labels: { boxWidth: 12, font: { size: 11 } },
          },
          tooltip: {
            callbacks: {
              label: (c) => {
                const pct = pcts[c.dataIndex];
                return ` ${c.label}: ${pct}% (${fmtCompact(c.parsed)} kgCO₂e)`;
              },
            },
          },
        },
      },
    });
  } catch (err) {
    setChartState("hotspotState", "error", `Failed to load: ${err.message}`);
  }
}

// --------------------------------------------------------------------------
// 4) Line - monthly total emissions
// --------------------------------------------------------------------------
async function renderTrend(year) {
  setChartState("trendState", "loading");
  $("trendYearTag").textContent = String(year);
  try {
    const rows = await api(`/api/analytics/monthly-trend?year=${year}`);
    destroyChart("trend");
    const hasData = rows.some((r) => r.total > 0);
    if (!hasData) {
      setChartState("trendState", "empty", "No monthly data for this year.");
      return;
    }
    setChartState("trendState", "hide");

    const labels = rows.map((r) => r.month_name);
    const total = rows.map((r) => r.total);
    const scope1 = rows.map((r) => r.scope1);
    const scope2 = rows.map((r) => r.scope2);

    charts.trend = new Chart($("trendChart"), {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "Total", data: total, borderColor: "#15803d",
            backgroundColor: "rgba(21,128,61,.12)", fill: true, tension: .3,
            borderWidth: 3, pointRadius: 3, pointBackgroundColor: "#15803d",
          },
          {
            label: "Scope 1", data: scope1, borderColor: SCOPE1_COLOR,
            backgroundColor: "transparent", borderDash: [5, 4], tension: .3,
            borderWidth: 2, pointRadius: 0,
          },
          {
            label: "Scope 2", data: scope2, borderColor: SCOPE2_COLOR,
            backgroundColor: "transparent", borderDash: [5, 4], tension: .3,
            borderWidth: 2, pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "bottom" },
          tooltip: {
            callbacks: { label: (c) => `${c.dataset.label}: ${fmtFull(c.parsed.y)} kgCO₂e` },
          },
        },
        scales: {
          x: { grid: { display: false } },
          y: { ticks: { callback: (v) => fmtCompact(v) }, title: { display: true, text: "kgCO₂e" } },
        },
      },
    });
  } catch (err) {
    setChartState("trendState", "error", `Failed to load: ${err.message}`);
  }
}

// --------------------------------------------------------------------------
// 3) KPI cards + intensity gauge
// --------------------------------------------------------------------------
async function renderKPIs(year) {
  // Year pills
  document.querySelectorAll("[data-year-pill]").forEach((el) => (el.textContent = year));

  // Placeholders while loading
  $("kpiTotal").textContent = "…";
  $("kpiYoY").textContent = "…";
  $("kpiIntensity").textContent = "…";
  $("kpiPerEmployee").textContent = "…";

  try {
    const [yoy, intensity] = await Promise.all([
      api(`/api/analytics/yoy?year=${year}`),
      api(`/api/analytics/intensity?year=${year}`),
    ]);

    // Total emissions
    $("kpiTotal").textContent = fmtCompact(yoy.current.total);
    $("kpiTotalScopes").innerHTML =
      `S1 ${fmtCompact(yoy.current.scope1)} &middot; S2 ${fmtCompact(yoy.current.scope2)}`;

    // YoY change
    $("kpiPrevYear").textContent = yoy.prev_year;
    const yoyEl = $("kpiYoY");
    if (yoy.change_pct === null || yoy.change_pct === undefined) {
      yoyEl.textContent = "n/a";
      yoyEl.className = "kpi-value delta-flat";
      $("kpiYoYAbs").textContent = "no prior-year baseline";
    } else {
      const arrow = yoy.change_pct > 0 ? "▲" : yoy.change_pct < 0 ? "▼" : "▬";
      yoyEl.textContent = `${arrow} ${fmtPct(yoy.change_pct)}`;
      yoyEl.className = "kpi-value " +
        (yoy.change_pct > 0 ? "delta-up" : yoy.change_pct < 0 ? "delta-down" : "delta-flat");
      const absDelta = yoy.current.total - yoy.previous.total;
      const sign = absDelta > 0 ? "+" : "";
      $("kpiYoYAbs").textContent = `${sign}${fmtCompact(absDelta)} kgCO₂e vs ${yoy.prev_year}`;
    }

    // Intensity (per ton of steel)
    const iEl = $("kpiIntensity");
    if (intensity.intensity_kgco2e_per_unit !== null && intensity.intensity_kgco2e_per_unit !== undefined) {
      iEl.textContent = fmtFull(intensity.intensity_kgco2e_per_unit, 1);
      const unit = intensity.production_unit || "unit";
      $("kpiIntensityUnit").innerHTML = `kgCO₂e per ${escapeHtml(unit)} of steel`;
    } else {
      iEl.textContent = "n/a";
      $("kpiIntensityUnit").textContent = "no production metric for this year";
    }

    // Gauge = current intensity relative to prior year (improvement => fuller green)
    const gauge = $("intensityGauge");
    const cap = $("intensityGaugeCaption");
    if (intensity.change_pct !== null && intensity.change_pct !== undefined) {
      // Map change_pct (typically -50..+50) into a 0..100 bar; lower is better.
      const clamped = Math.max(-50, Math.min(50, intensity.change_pct));
      const fill = Math.round(((50 - clamped) / 100) * 100); // -50% -> 100, +50% -> 0
      gauge.style.width = `${fill}%`;
      const dir = intensity.change_pct < 0 ? "improved" : intensity.change_pct > 0 ? "worsened" : "flat";
      cap.textContent = `${fmtPct(intensity.change_pct)} vs ${year - 1} (${dir})`;
    } else {
      gauge.style.width = "50%";
      cap.textContent = "no prior-year comparison";
    }

    // Per employee
    if (intensity.intensity_kgco2e_per_employee !== null && intensity.intensity_kgco2e_per_employee !== undefined) {
      $("kpiPerEmployee").textContent = fmtCompact(intensity.intensity_kgco2e_per_employee);
      $("kpiEmployees").textContent = intensity.employees
        ? `${fmtFull(intensity.employees)} employees`
        : "";
    } else {
      $("kpiPerEmployee").textContent = "n/a";
      $("kpiEmployees").textContent = "no headcount metric";
    }
  } catch (err) {
    $("kpiTotal").textContent = "err";
    $("kpiYoY").textContent = "err";
    $("kpiIntensity").textContent = "err";
    $("kpiPerEmployee").textContent = "err";
    showGlobalError(`KPI load failed: ${err.message}`);
  }
}

// --------------------------------------------------------------------------
// Records table + override
// --------------------------------------------------------------------------
function scopeBadge(scope) {
  return scope === 1
    ? `<span class="badge badge-s1">S1</span>`
    : `<span class="badge badge-s2">S2</span>`;
}

async function renderRecords(year) {
  const state = $("recordsState");
  state.className = "table-state";
  state.textContent = "Loading records…";
  $("recordsBody").innerHTML = "";
  try {
    const records = await api(`/api/records?year=${year}&limit=200`);
    $("recordsCountTag").textContent = `${records.length} shown`;
    const body = $("recordsBody");
    if (!records.length) {
      body.innerHTML = `<tr class="empty-row"><td colspan="10">No records for ${year}.</td></tr>`;
      state.textContent = "";
      return;
    }
    const rows = records.map((r) => {
      const status = r.is_overridden
        ? `<span class="badge badge-overridden">Overridden</span>`
        : `<span class="badge badge-calc">Calculated</span>`;
      const factor = r.factor_value_used !== null && r.factor_value_used !== undefined
        ? fmtFull(r.factor_value_used, 2)
        : "—";
      return `<tr>
        <td>${r.id}</td>
        <td>${escapeHtml(r.activity_date)}</td>
        <td>${scopeBadge(r.scope)}</td>
        <td>${escapeHtml(r.activity)}</td>
        <td class="num">${fmtFull(r.quantity, 2)}</td>
        <td>${escapeHtml(r.unit)}</td>
        <td class="num">${factor}</td>
        <td class="num">${fmtFull(r.final_emissions_kgco2e, 2)}</td>
        <td>${status}</td>
        <td><button class="btn-mini" data-override="${r.id}"
              data-current="${r.final_emissions_kgco2e}"
              data-activity="${escapeHtml(r.activity)}"
              data-date="${escapeHtml(r.activity_date)}">Override</button></td>
      </tr>`;
    });
    body.innerHTML = rows.join("");
    state.textContent = "";

    body.querySelectorAll("[data-override]").forEach((btn) => {
      btn.addEventListener("click", () => openOverrideModal(btn.dataset));
    });
  } catch (err) {
    state.className = "table-state err";
    state.textContent = `Failed to load records: ${err.message}`;
    $("recordsCountTag").textContent = "error";
  }
}

// --------------------------------------------------------------------------
// Audit log
// --------------------------------------------------------------------------
async function renderAuditLog() {
  const state = $("auditState");
  state.className = "table-state";
  state.textContent = "Loading audit log…";
  $("auditBody").innerHTML = "";
  try {
    const logs = await api(`/api/audit-log`);
    const body = $("auditBody");
    if (!logs.length) {
      body.innerHTML = `<tr class="empty-row"><td colspan="7">No overrides recorded yet.</td></tr>`;
      state.textContent = "";
      return;
    }
    body.innerHTML = logs.slice(0, 100).map((l) => `
      <tr>
        <td>${escapeHtml((l.changed_at || "").replace("T", " ").slice(0, 19))}</td>
        <td>#${l.record_id}</td>
        <td>${escapeHtml(l.action || "")}</td>
        <td class="num">${l.old_value !== null && l.old_value !== undefined ? fmtFull(Number(l.old_value), 2) : "—"}</td>
        <td class="num">${l.new_value !== null && l.new_value !== undefined ? fmtFull(Number(l.new_value), 2) : "—"}</td>
        <td>${escapeHtml(l.reason || "")}</td>
        <td>${escapeHtml(l.changed_by || "")}</td>
      </tr>`).join("");
    state.textContent = "";
  } catch (err) {
    state.className = "table-state err";
    state.textContent = `Failed to load audit log: ${err.message}`;
  }
}

// --------------------------------------------------------------------------
// Override modal
// --------------------------------------------------------------------------
let overrideTargetId = null;

function openOverrideModal(ds) {
  overrideTargetId = Number(ds.override);
  $("overrideContext").innerHTML =
    `Record <strong>#${overrideTargetId}</strong> &middot; ${escapeHtml(ds.activity)} ` +
    `(${escapeHtml(ds.date)})<br>Current final value: ` +
    `<strong>${fmtFull(Number(ds.current), 2)} kgCO₂e</strong>`;
  $("ovValue").value = Number(ds.current);
  $("ovReason").value = "";
  $("ovChangedBy").value = "";
  const result = $("overrideResult");
  result.hidden = true;
  result.className = "form-result";
  $("overrideModal").hidden = false;
}

function closeOverrideModal() {
  $("overrideModal").hidden = true;
  overrideTargetId = null;
}

async function submitOverride(ev) {
  ev.preventDefault();
  if (overrideTargetId === null) return;
  const btn = $("overrideSubmit");
  const result = $("overrideResult");
  btn.disabled = true;
  btn.textContent = "Applying…";
  try {
    const payload = {
      override_value: Number($("ovValue").value),
      reason: $("ovReason").value.trim(),
      changed_by: $("ovChangedBy").value.trim(),
    };
    const updated = await api(`/api/records/${overrideTargetId}/override`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    result.hidden = false;
    result.className = "form-result ok";
    result.innerHTML =
      `Override applied. Record <strong>#${updated.id}</strong> final value is now ` +
      `<span class="calc-figure">${fmtFull(updated.final_emissions_kgco2e, 2)} kgCO₂e</span>.`;
    // Refresh dependent views.
    await Promise.all([renderRecords(currentYear()), renderAuditLog()]);
    await refreshAnalytics(currentYear()); // overrides affect analytics
    setTimeout(closeOverrideModal, 1100);
  } catch (err) {
    result.hidden = false;
    result.className = "form-result err";
    result.textContent = `Override failed: ${err.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Apply Override";
  }
}

// --------------------------------------------------------------------------
// Forms: create record, create business metric
// --------------------------------------------------------------------------
async function submitRecord(ev) {
  ev.preventDefault();
  const btn = $("recSubmit");
  const result = $("recordResult");
  btn.disabled = true;
  btn.textContent = "Calculating…";
  result.hidden = true;
  try {
    const payload = {
      scope: Number($("recScope").value),
      activity: $("recActivity").value,
      category: $("recCategory").value.trim() || null,
      facility: $("recFacility").value.trim() || null,
      quantity: Number($("recQuantity").value),
      unit: $("recUnit").value.trim(),
      activity_date: $("recDate").value,
    };
    const rec = await api(`/api/records`, {
      method: "POST",
      body: JSON.stringify(payload),
    });

    // Look up the applied factor's version + validity window for transparency.
    let factorMeta = "";
    if (rec.factor_id) {
      try {
        const factors = await api(`/api/factors?activity=${encodeURIComponent(rec.activity)}`);
        const f = factors.find((x) => x.id === rec.factor_id);
        if (f) {
          const validTo = f.valid_to ? f.valid_to : "open-ended";
          factorMeta =
            `<span class="factor-meta">Factor applied: <strong>v${f.version}</strong> ` +
            `= ${fmtFull(f.co2e_per_unit, 2)} kgCO₂e/${escapeHtml(f.unit)} ` +
            `&middot; valid ${escapeHtml(f.valid_from)} → ${escapeHtml(validTo)} ` +
            `&middot; source: ${escapeHtml(f.source)}</span>`;
        }
      } catch { /* non-fatal: factor lookup is enrichment only */ }
    }
    if (!factorMeta) {
      factorMeta =
        `<span class="factor-meta">Factor value used: ` +
        `${rec.factor_value_used !== null ? fmtFull(rec.factor_value_used, 2) + " kgCO₂e/" + escapeHtml(rec.unit) : "none found"}.</span>`;
    }

    result.hidden = false;
    result.className = "form-result ok";
    result.innerHTML =
      `Record <strong>#${rec.id}</strong> saved. Engine-calculated emissions: ` +
      `<span class="calc-figure">${fmtFull(rec.calculated_emissions_kgco2e, 2)} kgCO₂e</span>.` +
      factorMeta;

    $("recQuantity").value = "";
    // Refresh records, audit + analytics if record falls in the selected year.
    const recYear = Number((payload.activity_date || "").slice(0, 4));
    await renderRecords(currentYear());
    if (recYear === currentYear()) {
      await refreshAnalytics(currentYear());
    }
  } catch (err) {
    result.hidden = false;
    result.className = "form-result err";
    result.textContent = `Could not save record: ${err.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Calculate & Save";
  }
}

async function submitMetric(ev) {
  ev.preventDefault();
  const btn = $("metSubmit");
  const result = $("metricResult");
  btn.disabled = true;
  btn.textContent = "Saving…";
  result.hidden = true;
  try {
    const payload = {
      metric_name: $("metName").value,
      value: Number($("metValue").value),
      unit: $("metUnit").value.trim() || null,
      metric_date: $("metDate").value,
    };
    const m = await api(`/api/business-metrics`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    result.hidden = false;
    result.className = "form-result ok";
    result.innerHTML =
      `Metric <strong>#${m.id}</strong> saved: ${escapeHtml(m.metric_name)} = ` +
      `<span class="calc-figure">${fmtFull(m.value, 2)}${m.unit ? " " + escapeHtml(m.unit) : ""}</span> ` +
      `for ${escapeHtml(m.metric_date)}.`;
    $("metValue").value = "";
    // Metrics drive intensity -> refresh KPIs if same year.
    const mYear = Number((payload.metric_date || "").slice(0, 4));
    if (mYear === currentYear()) await renderKPIs(currentYear());
  } catch (err) {
    result.hidden = false;
    result.className = "form-result err";
    result.textContent = `Could not save metric: ${err.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Save Metric";
  }
}

// --------------------------------------------------------------------------
// Orchestration
// --------------------------------------------------------------------------
function currentYear() { return Number($("yearSelect").value); }

function showGlobalError(msg) {
  const el = $("globalError");
  el.textContent = msg;
  el.hidden = false;
}
function clearGlobalError() { $("globalError").hidden = true; }
function showLoading(year) {
  $("loadingYear").textContent = year;
  $("globalLoading").hidden = false;
}
function hideLoading() { $("globalLoading").hidden = true; }

async function refreshAnalytics(year) {
  await Promise.all([
    renderKPIs(year),
    renderYoY(year),
    renderHotspot(year),
    renderTrend(year),
  ]);
}

async function refreshAll() {
  const year = currentYear();
  clearGlobalError();
  showLoading(year);
  try {
    await Promise.all([
      refreshAnalytics(year),
      renderRecords(year),
      renderAuditLog(),
    ]);
  } catch (err) {
    showGlobalError(`Dashboard load error: ${err.message}`);
  } finally {
    hideLoading();
  }
}

// --------------------------------------------------------------------------
// Wire up
// --------------------------------------------------------------------------
function init() {
  // Default form dates to today.
  $("recDate").value = todayISO();
  $("metDate").value = todayISO();

  // Year selector drives all analytics.
  $("yearSelect").addEventListener("change", refreshAll);
  $("refreshBtn").addEventListener("click", refreshAll);

  // Record form dynamic dropdown behaviour.
  $("recScope").addEventListener("change", populateActivityDropdown);
  $("recActivity").addEventListener("change", syncActivityDefaults);
  $("recordForm").addEventListener("submit", submitRecord);
  $("metricForm").addEventListener("submit", submitMetric);

  // Override modal.
  $("overrideForm").addEventListener("submit", submitOverride);
  $("overrideClose").addEventListener("click", closeOverrideModal);
  $("overrideCancel").addEventListener("click", closeOverrideModal);
  $("overrideModal").addEventListener("click", (e) => {
    if (e.target === $("overrideModal")) closeOverrideModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("overrideModal").hidden) closeOverrideModal();
  });

  // Load catalogue (for the record form), then load everything.
  loadFactorCatalogue().finally(refreshAll);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
