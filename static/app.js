/* Gulf AOR Dashboard — app.js */
'use strict';

// ─── State ───────────────────────────────────────────────────────────────────
let STATE = { indicators: [], airports: [], borders: [], outlook: {}, bm_tracking: {} };
let lastSavedAt = null;

const THREAT_LABELS = ['', 'Minimal', 'Low', 'Moderate', 'High', 'Critical'];
const TREND_META = {
  escalating:    { arrow: '↑', label: 'Escalating',    cls: 'trend-escalating' },
  stable:        { arrow: '→', label: 'Stable',         cls: 'trend-stable' },
  deescalating:  { arrow: '↓', label: 'De-escalating', cls: 'trend-deescalating' },
};

// ─── Startup ─────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  startClock();
  loadData();
  setInterval(updateSaveStatus, 5000);
});

function startClock() {
  const el = document.getElementById('utc-clock');
  function tick() {
    const now = new Date();
    const h = String(now.getUTCHours()).padStart(2,'0');
    const m = String(now.getUTCMinutes()).padStart(2,'0');
    const s = String(now.getUTCSeconds()).padStart(2,'0');
    el.textContent = `${h}:${m}:${s} UTC`;
  }
  tick();
  setInterval(tick, 1000);
}

// ─── API ─────────────────────────────────────────────────────────────────────
async function loadData() {
  try {
    const res = await fetch('/api/data');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    STATE.indicators  = data.indicators;
    STATE.airports    = data.airports;
    STATE.borders     = data.borders;
    STATE.outlook     = data.outlook;
    STATE.bm_tracking = data.bm_tracking;
    renderAll();
    document.getElementById('loading').classList.add('hidden');
    document.getElementById('last-updated').innerHTML =
      `LAST UPDATED <strong>${new Date().toUTCString().replace('GMT','Z')}</strong>`;
  } catch (e) {
    showToast('Failed to load data: ' + e.message, true);
    document.getElementById('loading').classList.add('hidden');
  }
}

async function apiPost(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`HTTP ${res.status}: ${txt}`);
  }
  return res.json();
}

// ─── Render All ──────────────────────────────────────────────────────────────
function renderAll() {
  renderIndicators();
  renderBMTracking();
  renderAirports();
  renderBorders();
  renderOutlook();
}

// ─── I&W Matrix ──────────────────────────────────────────────────────────────
function renderIndicators() {
  const tbody = document.getElementById('iw-tbody');
  const metCount   = STATE.indicators.filter(i => i.status === 'MET').length;
  const watchCount = STATE.indicators.filter(i => i.status === 'WATCH').length;
  const unmetCount = STATE.indicators.filter(i => i.status === 'UNMET').length;

  document.getElementById('iw-aggregate').innerHTML = `
    <div class="agg-item"><span class="agg-count agg-met">${metCount}</span><span>MET</span></div>
    <div class="agg-div">|</div>
    <div class="agg-item"><span class="agg-count agg-watch">${watchCount}</span><span>WATCH</span></div>
    <div class="agg-div">|</div>
    <div class="agg-item"><span class="agg-count agg-unmet">${unmetCount}</span><span>UNMET</span></div>
    <div class="agg-div">|</div>
    <div class="agg-item" style="color:var(--text-dim);font-size:0.72rem;">${metCount} of ${STATE.indicators.length} indicators MET</div>
  `;

  tbody.innerHTML = '';
  STATE.indicators.forEach(ind => {
    const tr = document.createElement('tr');
    tr.id = `iw-row-${ind.id}`;
    tr.innerHTML = buildIndicatorRow(ind);
    tbody.appendChild(tr);
  });
}

function buildIndicatorRow(ind) {
  const timeDisplay = ind.time_met
    ? `<span style="color:var(--text-dim);font-size:0.68rem;">${ind.time_met.replace('T',' ')}</span>`
    : '<span style="color:var(--border);">—</span>';
  return `
    <td class="num">${ind.id}</td>
    <td style="font-weight:500;">${escHtml(ind.indicator)}</td>
    <td><span class="status-pill status-${ind.status}">${ind.status}</span></td>
    <td>${timeDisplay}</td>
    <td class="notes-cell" title="${escHtml(ind.notes)}">${escHtml(ind.notes) || '<span style="color:var(--border)">—</span>'}</td>
    <td>
      <div class="btn-group">
        <button class="btn-edit" onclick="editIndicator(${ind.id})">✎ Edit</button>
      </div>
    </td>
  `;
}

function editIndicator(id) {
  const ind = STATE.indicators.find(i => i.id === id);
  if (!ind) return;
  const tr = document.getElementById(`iw-row-${id}`);
  tr.classList.add('edit-row');
  const statusOpts = ['MET','WATCH','UNMET'].map(s =>
    `<option value="${s}" ${ind.status===s?'selected':''}>${s}</option>`).join('');
  tr.innerHTML = `
    <td class="num">${ind.id}</td>
    <td style="font-weight:500;color:var(--text-dim);">${escHtml(ind.indicator)}</td>
    <td><select class="edit-select" id="edit-status-${id}">${statusOpts}</select></td>
    <td><input class="edit-input" type="text" id="edit-time-${id}" value="${escHtml(ind.time_met||'')}" placeholder="YYYY-MM-DDTHH:MM:SSZ"></td>
    <td><textarea class="edit-textarea" id="edit-notes-${id}">${escHtml(ind.notes)}</textarea></td>
    <td>
      <div class="btn-group">
        <button class="btn-save" onclick="saveIndicator(${id})">✓ Save</button>
        <button class="btn-cancel" onclick="cancelIndicatorEdit(${id})">✕</button>
      </div>
    </td>
  `;
}

async function saveIndicator(id) {
  const status   = document.getElementById(`edit-status-${id}`).value;
  const time_met = document.getElementById(`edit-time-${id}`).value.trim();
  const notes    = document.getElementById(`edit-notes-${id}`).value.trim();
  try {
    const res = await apiPost(`/api/indicators/${id}`, { status, time_met, notes });
    const ind = STATE.indicators.find(i => i.id === id);
    Object.assign(ind, res.indicator);
    renderIndicators();
    markSaved();
    showToast(`Indicator ${id} saved`);
  } catch (e) {
    showToast('Save failed: ' + e.message, true);
  }
}

function cancelIndicatorEdit(id) {
  const ind = STATE.indicators.find(i => i.id === id);
  const tr  = document.getElementById(`iw-row-${id}`);
  tr.classList.remove('edit-row');
  tr.innerHTML = buildIndicatorRow(ind);
}

// ─── BM Tracker ──────────────────────────────────────────────────────────────
function renderBMTracking() {
  const bm = STATE.bm_tracking;
  if (!bm || !bm.totals) return;

  const totals = bm.totals;
  const avgs   = bm.averages;
  const dep    = bm.depletion;

  // Badge
  const badge = document.getElementById('bm-badge');
  if (badge) badge.textContent = `Day ${totals.days_tracked}`;

  // Totals bar
  document.getElementById('bm-totals-bar').innerHTML = `
    <div class="bm-totals-bar">
      <div class="bm-total-item">
        <span class="bm-total-num bm-red">${totals.ballistic_missiles}</span>
        <span class="bm-total-label">Ballistic Missiles</span>
      </div>
      <div class="bm-total-div">+</div>
      <div class="bm-total-item">
        <span class="bm-total-num bm-amber">${totals.drones}</span>
        <span class="bm-total-label">Drones</span>
      </div>
      <div class="bm-total-div">+</div>
      <div class="bm-total-item">
        <span class="bm-total-num bm-amber">${totals.cruise_missiles}</span>
        <span class="bm-total-label">Cruise Missiles</span>
      </div>
      <div class="bm-total-div">=</div>
      <div class="bm-total-item">
        <span class="bm-total-num bm-total-all">${totals.total_projectiles}</span>
        <span class="bm-total-label">TOTAL PROJECTILES</span>
      </div>
      <div class="bm-total-sep"></div>
      <div class="bm-total-item">
        <span class="bm-total-num bm-avg">${avgs.bm_per_day}</span>
        <span class="bm-total-label">BM / Day (${totals.days_tracked}-day avg)</span>
      </div>
      <div class="bm-total-item">
        <span class="bm-total-num bm-avg">${avgs.total_per_day}</span>
        <span class="bm-total-label">Total / Day (avg)</span>
      </div>
    </div>
  `;

  // Daily log table
  const tbody = document.getElementById('bm-daily-tbody');
  tbody.innerHTML = '';
  (bm.daily_log || []).forEach(entry => {
    const bmAvg = avgs.bm_per_day;
    const diff  = entry.bm_announced - bmAvg;
    const diffStr = diff > 0
      ? `<span style="color:var(--red)">+${diff.toFixed(1)} ↑</span>`
      : diff < 0
        ? `<span style="color:var(--green)">${diff.toFixed(1)} ↓</span>`
        : `<span style="color:var(--text-dim)">avg</span>`;
    const confirmedBadge = entry.confirmed
      ? `<span class="status-pill status-OPEN" style="font-size:0.6rem;">CONFIRMED</span>`
      : `<span class="status-pill status-UNKNOWN" style="font-size:0.6rem;">EST.</span>`;
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="num">D${entry.day}</td>
      <td style="color:var(--text-dim);font-size:0.72rem;">${entry.date}</td>
      <td style="font-size:0.75rem;">${escHtml(entry.label)}</td>
      <td style="text-align:center;font-weight:700;color:var(--red);font-size:1.1rem;">${entry.bm_announced}</td>
      <td style="text-align:center;">${diffStr}</td>
      <td style="text-align:center;color:var(--amber);">${entry.drones_announced}</td>
      <td style="text-align:center;color:var(--text-dim);">${entry.cm_announced}</td>
      <td class="notes-cell" style="font-size:0.7rem;" title="${escHtml(entry.notes)}">${escHtml(entry.notes)}</td>
      <td style="text-align:center;">${confirmedBadge}</td>
    `;
    tbody.appendChild(tr);
  });

  // Averages footer row
  const tfoot = document.getElementById('bm-tfoot');
  tfoot.innerHTML = `
    <tr style="background:rgba(240,165,0,0.08);font-weight:600;">
      <td colspan="3" style="text-align:right;color:var(--amber);padding-right:8px;">4-DAY AVERAGE →</td>
      <td style="text-align:center;color:var(--amber);font-size:1.1rem;">${avgs.bm_per_day}</td>
      <td style="text-align:center;color:var(--text-dim);">baseline</td>
      <td style="text-align:center;color:var(--amber);">${avgs.drones_per_day}</td>
      <td style="text-align:center;color:var(--text-dim);">—</td>
      <td style="color:var(--text-dim);font-size:0.7rem;">Rolling ${totals.days_tracked}-day average</td>
      <td></td>
    </tr>
  `;

  // Depletion panel
  document.getElementById('bm-depletion-panel').innerHTML = `
    <div class="depletion-panel">
      <div class="depletion-header">⚠ INTERCEPTOR DEPLETION ANALYSIS (UAE)</div>
      <div class="depletion-grid">
        <div class="dep-item">
          <div class="dep-label">CURRENT INTERCEPT RATE</div>
          <div class="dep-val dep-watch">~${dep.uae_intercept_rate_pct}%</div>
        </div>
        <div class="dep-item">
          <div class="dep-label">DEGRADED RATE (PROJECTED)</div>
          <div class="dep-val dep-alert">~${dep.uae_intercept_rate_degraded_pct}%</div>
        </div>
        <div class="dep-item">
          <div class="dep-label">DEPLETION WINDOW</div>
          <div class="dep-val dep-alert">${escHtml(dep.uae_depletion_window)}</div>
        </div>
        <div class="dep-item">
          <div class="dep-label">RESUPPLY STATUS</div>
          <div class="dep-val dep-watch">${escHtml(dep.uae_resupply_status)}</div>
        </div>
      </div>
      <div class="dep-note">${escHtml(dep.bloomberg_assessment)}</div>
      <div class="dep-note dep-impact">${escHtml(dep.impact_if_degraded)}</div>
      <div class="dep-note" style="color:var(--text-dim);">${escHtml(dep.uae_official_position)}</div>
    </div>
  `;
}

// ─── Airports ────────────────────────────────────────────────────────────────
function renderAirports() {
  const grid = document.getElementById('airports-grid');
  grid.innerHTML = '';

  // STATE.airports is now grouped by country
  STATE.airports.forEach((group, gi) => {
    // Country label
    const countryDiv = document.createElement('div');
    countryDiv.className = 'airport-country-label';
    countryDiv.textContent = group.country;
    grid.appendChild(countryDiv);

    const groupGrid = document.createElement('div');
    groupGrid.className = 'airport-country-grid';
    grid.appendChild(groupGrid);

    group.airports.forEach((ap, ai) => {
      const div = document.createElement('div');
      div.className = 'airport-card';
      div.id = `ap-card-${gi}-${ai}`;
      div.innerHTML = buildAirportCard(ap, gi, ai);
      groupGrid.appendChild(div);
    });
  });
}

function buildAirportCard(ap, gi, ai) {
  return `
    <div>
      <span class="icao">${ap.icao}</span><span class="iata">/ ${ap.iata}</span>
    </div>
    <div class="airport-name">${escHtml(ap.name)}</div>
    <div class="airport-city">${escHtml(ap.city)}</div>
    <div class="airport-status">
      <span class="status-pill status-${ap.status}">${ap.status}</span>
    </div>
    <div class="airport-notes">${escHtml(ap.notes)}</div>
    <div class="card-edit-btn">
      <button class="btn-edit" onclick="editAirport(${gi},${ai})">✎</button>
    </div>
  `;
}

function editAirport(gi, ai) {
  const ap  = STATE.airports[gi].airports[ai];
  const div = document.getElementById(`ap-card-${gi}-${ai}`);
  const statusOpts = ['OPEN','RESTRICTED','CLOSED','UNKNOWN'].map(s =>
    `<option value="${s}" ${ap.status===s?'selected':''}>${s}</option>`).join('');
  div.innerHTML = `
    <div>
      <span class="icao">${ap.icao}</span><span class="iata">/ ${ap.iata}</span>
    </div>
    <div class="airport-name" style="color:var(--text-dim);">${escHtml(ap.name)}</div>
    <div class="airport-edit-form">
      <select class="edit-select" id="ap-status-${gi}-${ai}">${statusOpts}</select>
      <textarea class="edit-textarea" id="ap-notes-${gi}-${ai}">${escHtml(ap.notes)}</textarea>
      <div class="btn-group">
        <button class="btn-save" onclick="saveAirport(${gi},${ai})">✓ Save</button>
        <button class="btn-cancel" onclick="cancelAirportEdit(${gi},${ai})">✕</button>
      </div>
    </div>
  `;
}

async function saveAirport(gi, ai) {
  const status = document.getElementById(`ap-status-${gi}-${ai}`).value;
  const notes  = document.getElementById(`ap-notes-${gi}-${ai}`).value.trim();
  STATE.airports[gi].airports[ai].status = status;
  STATE.airports[gi].airports[ai].notes  = notes;
  try {
    await apiPost('/api/update', { section: 'airports', data: STATE.airports });
    renderAirports();
    markSaved();
    showToast(`${STATE.airports[gi].airports[ai].icao} saved`);
  } catch (e) {
    showToast('Save failed: ' + e.message, true);
  }
}

function cancelAirportEdit(gi, ai) {
  const div = document.getElementById(`ap-card-${gi}-${ai}`);
  div.innerHTML = buildAirportCard(STATE.airports[gi].airports[ai], gi, ai);
}

// ─── Borders ─────────────────────────────────────────────────────────────────
function renderBorders() {
  const tbody = document.getElementById('borders-tbody');
  tbody.innerHTML = '';
  STATE.borders.forEach((group, gi) => {
    const hdr = document.createElement('tr');
    hdr.className = 'country-group';
    hdr.innerHTML = `<td class="country-label" colspan="4">${escHtml(group.country)}</td>`;
    tbody.appendChild(hdr);
    group.crossings.forEach((crossing, ci) => {
      const tr = document.createElement('tr');
      tr.id = `border-row-${gi}-${ci}`;
      tr.innerHTML = buildBorderRow(crossing, gi, ci);
      tbody.appendChild(tr);
    });
  });
}

function buildBorderRow(c, gi, ci) {
  return `
    <td style="padding-left:24px;font-weight:500;">${escHtml(c.name)}</td>
    <td><span class="status-pill status-${c.status}">${c.status}</span></td>
    <td class="notes-cell" title="${escHtml(c.notes)}">${escHtml(c.notes) || '<span style="color:var(--border)">—</span>'}</td>
    <td><button class="btn-edit" onclick="editBorder(${gi},${ci})">✎ Edit</button></td>
  `;
}

function editBorder(gi, ci) {
  const c  = STATE.borders[gi].crossings[ci];
  const tr = document.getElementById(`border-row-${gi}-${ci}`);
  tr.classList.add('edit-row');
  const statusOpts = ['OPEN','RESTRICTED','CLOSED','UNKNOWN'].map(s =>
    `<option value="${s}" ${c.status===s?'selected':''}>${s}</option>`).join('');
  tr.innerHTML = `
    <td style="padding-left:24px;font-weight:500;color:var(--text-dim);">${escHtml(c.name)}</td>
    <td><select class="edit-select" id="border-status-${gi}-${ci}">${statusOpts}</select></td>
    <td><textarea class="edit-textarea" id="border-notes-${gi}-${ci}">${escHtml(c.notes)}</textarea></td>
    <td>
      <div class="btn-group">
        <button class="btn-save" onclick="saveBorder(${gi},${ci})">✓ Save</button>
        <button class="btn-cancel" onclick="cancelBorderEdit(${gi},${ci})">✕</button>
      </div>
    </td>
  `;
}

async function saveBorder(gi, ci) {
  const status = document.getElementById(`border-status-${gi}-${ci}`).value;
  const notes  = document.getElementById(`border-notes-${gi}-${ci}`).value.trim();
  STATE.borders[gi].crossings[ci].status = status;
  STATE.borders[gi].crossings[ci].notes  = notes;
  try {
    await apiPost('/api/update', { section: 'borders', data: STATE.borders });
    renderBorders();
    markSaved();
    showToast(`${STATE.borders[gi].crossings[ci].name} saved`);
  } catch (e) {
    showToast('Save failed: ' + e.message, true);
  }
}

function cancelBorderEdit(gi, ci) {
  const c  = STATE.borders[gi].crossings[ci];
  const tr = document.getElementById(`border-row-${gi}-${ci}`);
  tr.classList.remove('edit-row');
  tr.innerHTML = buildBorderRow(c, gi, ci);
}

// ─── Outlook ─────────────────────────────────────────────────────────────────
function renderOutlook() {
  ['short','medium','long'].forEach(key => {
    const o   = STATE.outlook[key];
    if (!o) return;
    const div = document.getElementById(`outlook-${key}`);
    div.innerHTML = buildOutlookCard(o, key);
  });
}

function buildOutlookCard(o, key) {
  const tl   = o.threat_level;
  const tm   = TREND_META[o.trend] || TREND_META['stable'];
  const driversHtml = (o.key_drivers || []).map(d => `<li>${escHtml(d)}</li>`).join('');
  const threatBtns = [1,2,3,4,5].map(n =>
    `<button class="threat-btn ${n===tl?'active-'+n:''}"
      onclick="setThreatLevel('${key}',${n})"
      title="${THREAT_LABELS[n]}">${n}</button>`
  ).join('');
  return `
    <div class="outlook-header">
      <div class="outlook-title">${escHtml(o.label || o.period)}</div>
      <button class="btn-edit" onclick="editOutlook('${key}')">✎ Edit</button>
    </div>
    <div class="outlook-body">
      <div class="threat-row">
        <span class="threat-label">THREAT LVL</span>
        <div class="threat-selector">${threatBtns}</div>
        <span class="threat-text tl-${tl}">${THREAT_LABELS[tl]}</span>
      </div>
      <div class="trend-row">
        <span class="threat-label">TREND</span>
        <span class="trend-indicator ${tm.cls}">${tm.arrow}</span>
        <span class="trend-label-text">${tm.label}</span>
      </div>
      <div class="outlook-section-label">Analyst Assessment</div>
      <div class="outlook-assessment">${escHtml(o.assessment)}</div>
      <div class="outlook-section-label">Key Drivers</div>
      <ul class="outlook-drivers">${driversHtml}</ul>
      <div class="outlook-footer">Last updated: ${escHtml(o.last_updated)}</div>
    </div>
  `;
}

async function setThreatLevel(key, level) {
  STATE.outlook[key].threat_level = level;
  STATE.outlook[key].last_updated = new Date().toISOString().replace(/\.\d{3}Z/, 'Z');
  try {
    await apiPost('/api/update', { section: 'outlook', data: STATE.outlook });
    renderOutlook();
    markSaved();
    showToast('Threat level updated');
  } catch (e) {
    showToast('Save failed: ' + e.message, true);
  }
}

function editOutlook(key) {
  const o   = STATE.outlook[key];
  const div = document.getElementById(`outlook-${key}`);
  const trendBtns = Object.entries(TREND_META).map(([k, v]) =>
    `<button class="trend-select-btn ${o.trend===k?'selected-'+k:''}"
      id="trend-btn-${key}-${k}"
      onclick="selectTrend('${key}','${k}')">${v.arrow} ${v.label}</button>`
  ).join('');
  const driversText = (o.key_drivers || []).join('\n');
  div.innerHTML = `
    <div class="outlook-header">
      <div class="outlook-title">${escHtml(o.label || o.period)}</div>
      <div class="btn-group">
        <button class="btn-save" onclick="saveOutlook('${key}')">✓ Save</button>
        <button class="btn-cancel" onclick="renderOutlook()">✕</button>
      </div>
    </div>
    <div class="outlook-body">
      <div class="outlook-section-label">Threat Level (1-5)</div>
      <div class="threat-selector" style="margin-bottom:10px;">
        ${[1,2,3,4,5].map(n =>
          `<button class="threat-btn ${n===o.threat_level?'active-'+n:''}"
            id="tl-edit-${key}-${n}"
            onclick="selectThreatEdit('${key}',${n})">${n}</button>`
        ).join('')}
      </div>
      <div class="outlook-section-label">Trend</div>
      <div class="trend-select-group" style="margin-bottom:10px;">${trendBtns}</div>
      <div class="outlook-section-label">Analyst Assessment</div>
      <textarea class="edit-textarea" id="edit-assessment-${key}" style="min-height:80px;">${escHtml(o.assessment)}</textarea>
      <div class="outlook-section-label">Key Drivers (one per line)</div>
      <textarea class="edit-textarea" id="edit-drivers-${key}" style="min-height:80px;">${escHtml(driversText)}</textarea>
    </div>
  `;
  div._editThreat = o.threat_level;
  div._editTrend  = o.trend;
}

function selectThreatEdit(key, level) {
  const div = document.getElementById(`outlook-${key}`);
  div._editThreat = level;
  [1,2,3,4,5].forEach(n => {
    const btn = document.getElementById(`tl-edit-${key}-${n}`);
    if (btn) btn.className = `threat-btn ${n===level?'active-'+n:''}`;
  });
}

function selectTrend(key, trend) {
  const div = document.getElementById(`outlook-${key}`);
  div._editTrend = trend;
  Object.keys(TREND_META).forEach(k => {
    const btn = document.getElementById(`trend-btn-${key}-${k}`);
    if (btn) btn.className = `trend-select-btn ${k===trend?'selected-'+k:''}`;
  });
}

async function saveOutlook(key) {
  const div        = document.getElementById(`outlook-${key}`);
  const assessment = document.getElementById(`edit-assessment-${key}`).value.trim();
  const driversRaw = document.getElementById(`edit-drivers-${key}`).value;
  const drivers    = driversRaw.split('\n').map(l => l.trim()).filter(Boolean);
  const tl         = div._editThreat || STATE.outlook[key].threat_level;
  const trend      = div._editTrend  || STATE.outlook[key].trend;
  STATE.outlook[key] = {
    ...STATE.outlook[key],
    threat_level: tl,
    trend,
    assessment,
    key_drivers: drivers,
    last_updated: new Date().toISOString().replace(/\.\d{3}Z/, 'Z'),
  };
  try {
    await apiPost('/api/update', { section: 'outlook', data: STATE.outlook });
    renderOutlook();
    markSaved();
    showToast('Outlook updated');
  } catch (e) {
    showToast('Save failed: ' + e.message, true);
  }
}

// ─── Reset ───────────────────────────────────────────────────────────────────
async function resetDefaults() {
  if (!confirm('Reset ALL data to factory defaults? This cannot be undone.')) return;
  try {
    await apiPost('/api/reset', {});
    await loadData();
    showToast('Reset to defaults complete');
  } catch (e) {
    showToast('Reset failed: ' + e.message, true);
  }
}

// ─── Utility ─────────────────────────────────────────────────────────────────
function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}

function markSaved() {
  lastSavedAt = Date.now();
  updateSaveStatus();
}

function updateSaveStatus() {
  const el = document.getElementById('save-status');
  if (!lastSavedAt) { el.textContent = ''; return; }
  const sec = Math.round((Date.now() - lastSavedAt) / 1000);
  if (sec < 5)  { el.textContent = '✓ Saved'; el.style.color = 'var(--green)'; }
  else if (sec < 60) { el.textContent = `Last saved: ${sec}s ago`; el.style.color = 'var(--text-dim)'; }
  else { const m = Math.round(sec/60); el.textContent = `Last saved: ${m}m ago`; el.style.color = 'var(--text-dim)'; }
}

let toastTimer = null;
function showToast(msg, isError = false) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast' + (isError ? ' error' : '');
  void el.offsetWidth;
  el.classList.add('show');
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 3000);
}
