/* Gulf AOR Dashboard — app.js (multi-page) */
'use strict';

// ── Page detection ──────────────────────────────────────────────────────────
const PAGE      = document.body.dataset.page   || 'landing';
const AREA_SLUG = document.body.dataset.area   || '';

const SEVERITY_ORDER = { critical: 0, high: 1, medium: 2, low: 3 };
const RISK_CLASS = {
  'CRITICAL':     'risk-critical',
  'HIGH':         'risk-high',
  'MODERATE':     'risk-moderate',
  'LOW-MODERATE': 'risk-low-moderate',
  'LOW':          'risk-low',
};

// ── Startup ─────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  startClock();
  if (PAGE === 'landing') {
    initLanding();
  } else if (PAGE === 'country') {
    initCountry();
  }
  initCommentWidget();
});

// ── UTC Clock ────────────────────────────────────────────────────────────────
function startClock() {
  const el = document.getElementById('utc-clock');
  if (!el) return;
  function tick() {
    const n = new Date();
    const h = String(n.getUTCHours()).padStart(2, '0');
    const m = String(n.getUTCMinutes()).padStart(2, '0');
    const s = String(n.getUTCSeconds()).padStart(2, '0');
    el.textContent = `UTC ${h}:${m}:${s}`;
  }
  tick();
  setInterval(tick, 1000);
}

// ══════════════════════════════════════════════════════════════════════════════
//  LANDING PAGE
// ══════════════════════════════════════════════════════════════════════════════
async function initLanding() {
  try {
    const res = await fetch('/api/macro');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    renderLandingAirports(data.airports, data.fr24_meta);
    renderMacroIW(data.macro_indicators);
    renderBMTracking(data.bm_tracking);
    renderStateDeptStrip(data.state_dept);
    updateRefreshLabel(data.server_time);
    hideLoading();
  } catch (e) {
    showToast('Failed to load macro data: ' + e.message, true);
    hideLoading();
  }
}

// ── Landing: Airport Status ───────────────────────────────────────────────────
function renderLandingAirports(airportGroups, fr24Meta) {
  const el      = document.getElementById('landing-airports');
  const badgeEl = document.getElementById('airport-summary-badge');
  if (!el) return;
  if (!airportGroups || !airportGroups.length) {
    el.innerHTML = '<div class="feed-empty">No airport data</div>';
    return;
  }

  // Summary badge
  const all = airportGroups.flatMap(g => g.airports || []);
  const open   = all.filter(a => a.status === 'OPEN').length;
  const obstr  = all.filter(a => a.status === 'OBSTRUCTED').length;
  const closed = all.filter(a => a.status === 'CLOSED').length;
  if (badgeEl) badgeEl.innerHTML =
    `<span style="color:var(--green)">${open} OPEN</span> &nbsp;` +
    `<span style="color:var(--amber)">${obstr} OBSTR</span> &nbsp;` +
    `<span style="color:var(--red)">${closed} CLOSED</span>`;

  const STATUS_ICON = { OPEN:'🟢', OBSTRUCTED:'🟡', CLOSED:'🔴' };
  const STATUS_COLOR = { OPEN:'var(--green)', OBSTRUCTED:'var(--amber)', CLOSED:'var(--red)' };

  // FR24 scan metadata bar
  let metaBar = '';
  if (fr24Meta && fr24Meta.last_scan_utc) {
    const scanAge  = Math.round((Date.now() - new Date(fr24Meta.last_scan_utc).getTime()) / 60000);
    const capWarn  = fr24Meta.capped
      ? `<span style="color:var(--amber)">⚠ response cap (20) reached</span>` : '';
    const totalStr = `${fr24Meta.total_gulf_flights ?? '?'} flights in AOR`;
    metaBar = `<div class="fr24-meta-bar">FR24 · ${totalStr} · scan ${scanAge}m ago ${capWarn}</div>`;
  }
  el.innerHTML = metaBar + airportGroups.map(group => `
    <div class="ap-country-group">
      <div class="ap-country-label">${escHtml(group.country)}</div>
      ${(group.airports || []).map(ap => {
        const icon  = STATUS_ICON[ap.status]  || '⚪';
        const color = STATUS_COLOR[ap.status] || 'var(--text-dim)';
        const canceled = ap.all_canceled
          ? `<span class="ap-canceled-pill">100% CANCELED</span>` : '';
        const airspace = ap.airspace
          ? `<span class="ap-airspace">${escHtml(ap.airspace)}</span>` : '';
        const liveCount = ap.live_flights !== undefined && ap.live_flights !== null
          ? ap.live_flights : '—';
        const liveColor = liveCount === 0 ? 'var(--red)'
                        : liveCount === '—' ? 'var(--text-dim)'
                        : 'var(--green)';
        const liveStr = `<span class="ap-live-flights" style="color:${liveColor}" title="FR24 live flights near airport">✈ ${liveCount} live</span>`;

        // Intl / Domestic cancellation indicators
        const intlC = ap.intl_canceled
          ? `<span class="ap-ops-pill ${ap.intl_canceled.startsWith('No') ? 'ops-ok' : 'ops-canceled'}">INTL: ${escHtml(ap.intl_canceled)}</span>` : '';
        const domC  = ap.domestic_canceled
          ? `<span class="ap-ops-pill ${ap.domestic_canceled.startsWith('No') ? 'ops-ok' : 'ops-canceled'}">DOM: ${escHtml(ap.domestic_canceled)}</span>` : '';

        return `
        <div class="ap-row">
          <div class="ap-row-top">
            <span class="ap-iata" style="color:${color}">${icon} ${escHtml(ap.iata)}</span>
            <span class="ap-status-pill status-${ap.status}">${ap.status}</span>
            ${canceled}
            ${liveStr}
          </div>
          <div class="ap-row-ops">
            ${intlC}${domC}
            ${airspace}
          </div>
          ${ap.notes ? `<div class="ap-notes">${escHtml(ap.notes)}</div>` : ''}
        </div>`;
      }).join('')}
    </div>`
  ).join('');
}

// ── Activity Feed ────────────────────────────────────────────────────────────
function renderActivityFeed(events, containerId, countId) {
  const el = document.getElementById(containerId);
  const countEl = document.getElementById(countId);
  if (!el) return;

  const sorted = [...events].sort((a, b) => {
    // Primary: severity, secondary: timestamp desc
    const sa = SEVERITY_ORDER[a.severity] ?? 9;
    const sb = SEVERITY_ORDER[b.severity] ?? 9;
    if (sa !== sb) return sa - sb;
    return new Date(b.ts_utc) - new Date(a.ts_utc);
  });

  if (countEl) countEl.textContent = `${sorted.length} events`;

  if (sorted.length === 0) {
    el.innerHTML = '<div class="feed-empty">No activity recorded</div>';
    return;
  }

  el.innerHTML = sorted.map(evt => {
    const ts = formatTs(evt.ts_utc);
    const countries = (evt.countries || [])
      .filter(c => c !== 'macro')
      .map(c => `<span class="evt-country">${c.toUpperCase()}</span>`)
      .join('');
    return `
      <div class="evt-card sev-${evt.severity}">
        <div class="evt-header">
          <span class="evt-sev sev-pill-${evt.severity}">${(evt.severity||'').toUpperCase()}</span>
          ${countries}
          <span class="evt-ts">${ts}</span>
        </div>
        <div class="evt-title">${escHtml(evt.title)}</div>
        <div class="evt-summary">${escHtml(evt.summary)}</div>
        ${evt.source ? `<div class="evt-source">Source: ${escHtml(evt.source)}</div>` : ''}
      </div>`;
  }).join('');
}

// ── Macro I&W ────────────────────────────────────────────────────────────────
function renderMacroIW(indicators) {
  const el = document.getElementById('iw-macro-list');
  const countEl = document.getElementById('iw-macro-count');
  if (!el) return;

  const met   = indicators.filter(i => i.status === 'MET').length;
  const watch = indicators.filter(i => i.status === 'WATCH').length;
  const unmet = indicators.filter(i => i.status === 'UNMET').length;
  if (countEl) countEl.innerHTML =
    `<span class="agg-met">${met} MET</span> &nbsp;
     <span class="agg-watch">${watch} WATCH</span> &nbsp;
     <span class="agg-unmet">${unmet} UNMET</span>`;

  el.innerHTML = indicators.map(ind => `
    <div class="iw-row">
      <div class="iw-row-top">
        <span class="iw-name">${escHtml(ind.name)}</span>
        <span class="status-pill status-${ind.status}">${ind.status}</span>
      </div>
      <div class="iw-desc">${escHtml(ind.description)}</div>
      ${ind.notes ? `<div class="iw-notes">${escHtml(ind.notes)}</div>` : ''}
      <div class="iw-updated">${formatTs(ind.last_updated)}</div>
    </div>
  `).join('');
}

// ── BM Tracker ───────────────────────────────────────────────────────────────
function renderBMTracking(bm) {
  if (!bm || !bm.totals) return;
  const totals = bm.totals;
  const avgs   = bm.averages;
  const dep    = bm.depletion;

  const badge = document.getElementById('bm-badge');
  if (badge) badge.textContent = `Day ${totals.days_tracked}`;

  const totalsBar = document.getElementById('bm-totals-bar');
  if (totalsBar) {
    totalsBar.innerHTML = `
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
          <span class="bm-total-label">Total Projectiles</span>
        </div>
        <div class="bm-total-sep"></div>
        <div class="bm-total-item">
          <span class="bm-total-num bm-avg">${avgs.bm_per_day}</span>
          <span class="bm-total-label">BM / Day (avg)</span>
        </div>
        <div class="bm-total-item">
          <span class="bm-total-num bm-avg">${avgs.total_per_day}</span>
          <span class="bm-total-label">Total / Day (avg)</span>
        </div>
      </div>`;
  }

  const tbody = document.getElementById('bm-daily-tbody');
  if (tbody) {
    tbody.innerHTML = '';
    (bm.daily_log || []).forEach(entry => {
      const diff = entry.bm_announced - avgs.bm_per_day;
      const diffStr = diff > 0
        ? `<span style="color:var(--red)">+${diff.toFixed(1)} ↑</span>`
        : diff < 0
          ? `<span style="color:var(--green)">${diff.toFixed(1)} ↓</span>`
          : `<span style="color:var(--text-dim)">avg</span>`;
      const conf = entry.confirmed
        ? `<span class="status-pill status-OPEN" style="font-size:.6rem">CONF</span>`
        : `<span class="status-pill status-UNKNOWN" style="font-size:.6rem">EST</span>`;
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td class="num">D${entry.day}</td>
        <td style="color:var(--text-dim);font-size:.72rem">${entry.date}</td>
        <td style="font-size:.75rem">${escHtml(entry.label)}</td>
        <td style="text-align:center;font-weight:700;color:var(--red);font-size:1.1rem">${entry.bm_announced}</td>
        <td style="text-align:center">${diffStr}</td>
        <td style="text-align:center;color:var(--amber)">${entry.drones_announced}</td>
        <td style="text-align:center;color:var(--text-dim)">${entry.cm_announced}</td>
        <td class="notes-cell" style="font-size:.7rem" title="${escHtml(entry.notes)}">${escHtml(entry.notes)}</td>
        <td style="text-align:center">${conf}</td>`;
      tbody.appendChild(tr);
    });
  }

  const tfoot = document.getElementById('bm-tfoot');
  if (tfoot) {
    tfoot.innerHTML = `
      <tr style="background:rgba(240,165,0,.08);font-weight:600">
        <td colspan="3" style="text-align:right;color:var(--amber);padding-right:8px">
          ${totals.days_tracked}-DAY AVERAGE →
        </td>
        <td style="text-align:center;color:var(--amber);font-size:1.1rem">${avgs.bm_per_day}</td>
        <td style="text-align:center;color:var(--text-dim)">baseline</td>
        <td style="text-align:center;color:var(--amber)">${avgs.drones_per_day}</td>
        <td colspan="3"></td>
      </tr>`;
  }

  const depPanel = document.getElementById('bm-depletion-panel');
  if (depPanel && dep) {
    depPanel.innerHTML = `
      <div class="depletion-panel">
        <div class="depletion-header">INTERCEPTOR DEPLETION ANALYSIS (UAE)</div>
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
        <div class="dep-note" style="color:var(--text-dim)">${escHtml(dep.uae_official_position)}</div>
      </div>`;
  }
}

// ══════════════════════════════════════════════════════════════════════════════
//  COUNTRY PAGE
// ══════════════════════════════════════════════════════════════════════════════
async function initCountry() {
  try {
    const res = await fetch(`/api/area/${AREA_SLUG}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    renderCountryHero(data.area);
    renderIWMatrix(data.iw_matrix || []);
    renderStateDeptCountry(data.state_dept);
    renderKeyPoints(data.area.key_points);
    renderSituationUpdate(data.area);
    renderCountryAirports(data.area.airports);
    renderCountryBorders(data.area.borders);
    renderEvacRoutes(data.area);
    updateRefreshLabel(data.server_time);
    hideLoading();
  } catch (e) {
    showToast('Failed to load area data: ' + e.message, true);
    hideLoading();
  }
}

function renderIWMatrix(matrix) {
  const tbody  = document.getElementById('iw-country-tbody');
  const countEl = document.getElementById('iw-country-count');
  if (!tbody) return;

  if (!matrix || matrix.length === 0) {
    tbody.innerHTML = '<tr><td colspan="3" class="feed-empty">No I&amp;W data</td></tr>';
    return;
  }

  const met   = matrix.filter(r => r.status === 'MET').length;
  const watch = matrix.filter(r => r.status === 'WATCH').length;
  const unmet = matrix.filter(r => ['UNMET','LOW'].includes(r.status)).length;
  if (countEl) countEl.innerHTML =
    `<span class="agg-met">${met} MET</span> &nbsp;` +
    `<span class="agg-watch">${watch} WATCH</span> &nbsp;` +
    `<span class="agg-unmet">${unmet} UNMET</span>`;

  tbody.innerHTML = matrix.map(row => {
    const s = row.status || 'UNKNOWN';
    return `
      <tr class="iw-matrix-row">
        <td class="iw-matrix-indicator">${escHtml(row.indicator)}</td>
        <td style="text-align:center">
          <span class="status-pill status-${s}">${s}</span>
        </td>
        <td class="iw-matrix-notes">${escHtml(row.notes || '')}</td>
      </tr>`;
  }).join('');
}

function renderCountryHero(area) {
  const updated = document.getElementById('country-updated');
  if (updated) updated.textContent = `Last updated: ${formatTs(area.last_updated)}`;

  const pills = document.getElementById('country-status-pills');
  if (!pills) return;

  const rows = area?.situation_assessment || [];
  const threat = (rows.find(r => (r.category || '').toLowerCase() === 'current threat') || {}).assessment || '';
  const trend  = (rows.find(r => (r.category || '').toLowerCase() === 'threat trend') || {}).assessment || '';

  const threatWord = (threat.split(/\s|\./)[0] || '').toUpperCase();
  const trendWord  = (trend.split(/\s|\./)[0] || '').toUpperCase();

  function mapThreat(word) {
    if (['EXTREME', 'HIGH'].includes(word)) return 'MET';
    if (['MODERATE'].includes(word)) return 'WATCH';
    if (['LOW'].includes(word)) return 'UNMET';
    return 'UNKNOWN';
  }
  function mapTrend(word) {
    if (['RAPIDLY', 'ESCALATING', 'INCREASING'].includes(word)) return 'WATCH';
    if (['STABLE'].includes(word)) return 'UNMET';
    return 'UNKNOWN';
  }

  const threatPill = mapThreat(threatWord);
  const trendPill  = mapTrend(trendWord);

  pills.innerHTML = `
    <div class="hero-pill-group">
      <span class="hero-pill-label">THREAT</span>
      <span class="status-pill status-${threatPill}">${escHtml(threatWord || '—')}</span>
    </div>
    <div class="hero-pill-group">
      <span class="hero-pill-label">TREND</span>
      <span class="status-pill status-${trendPill}">${escHtml(trendWord || '—')}</span>
    </div>`;
}

function renderKeyPoints(points) {
  const el = document.getElementById('key-points-list');
  if (!el) return;
  if (!points || !points.length) {
    el.innerHTML = '<li class="feed-empty">No key points recorded</li>';
    return;
  }
  el.innerHTML = points.map(p => `<li>${escHtml(p)}</li>`).join('');
}

function renderSituationUpdate(area) {
  const panel = document.getElementById('country-situation-panel');
  const badge = document.getElementById('situation-updated-badge');
  if (!panel) return;

  const rows = area?.situation_assessment || [];
  const updated = area?.situation_last_updated || area?.last_updated;
  if (badge) badge.textContent = updated ? `Updated: ${formatTs(updated)}` : '—';

  if (!rows.length) {
    panel.innerHTML = '<div class="feed-empty">No situation update yet for this country.</div>';
    return;
  }

  panel.innerHTML = `
    <table style="width:100%;border-collapse:collapse">
      <thead>
        <tr>
          <th style="text-align:left;padding:8px;border-bottom:1px solid #30363d;width:34%">Category</th>
          <th style="text-align:left;padding:8px;border-bottom:1px solid #30363d">Assessment</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map(r => `
          <tr>
            <td style="vertical-align:top;padding:8px;border-bottom:1px solid #21262d;font-weight:600">${escHtml(r.category || '')}</td>
            <td style="vertical-align:top;padding:8px;border-bottom:1px solid #21262d">${escHtml(r.assessment || '')}</td>
          </tr>`).join('')}
      </tbody>
    </table>
  `;
}

function renderCountryAirports(airports) {
  const grid = document.getElementById('country-airports');
  const badge = document.getElementById('ap-status-badge');
  if (!grid) return;

  const open = airports.filter(a =>
    a.status === 'OPEN' || a.status === 'WATCH' || a.status === 'DEGRADED').length;
  const closed = airports.filter(a => a.status === 'CLOSED').length;

  if (badge) badge.textContent =
    `${open} operational · ${closed} closed of ${airports.length}`;

  grid.innerHTML = airports.map(ap => `
    <div class="airport-card">
      <div>
        <span class="icao">${ap.icao}</span>
        <span class="iata">/ ${ap.iata}</span>
      </div>
      <div class="airport-name">${escHtml(ap.name)}</div>
      <div class="airport-city">${escHtml(ap.city)}</div>
      <div class="airport-status">
        <span class="status-pill status-${ap.status}">${ap.status}</span>
      </div>
      <div class="airport-notes">${escHtml(ap.notes)}</div>
    </div>`).join('');
}

function renderCountryBorders(borders) {
  const tbody = document.getElementById('country-borders-tbody');
  const badge = document.getElementById('border-status-badge');
  if (!tbody) return;

  if (!borders || !borders.length) {
    tbody.innerHTML = '<tr><td colspan="3" class="feed-empty">No land borders</td></tr>';
    if (badge) badge.textContent = 'Island / no land borders';
    return;
  }

  const open   = borders.filter(b => b.status === 'OPEN').length;
  const closed = borders.filter(b => b.status === 'CLOSED').length;
  if (badge) badge.textContent = `${open} open · ${closed} closed of ${borders.length}`;

  tbody.innerHTML = borders.map(b => `
    <tr>
      <td style="font-weight:500">${escHtml(b.name)}</td>
      <td><span class="status-pill status-${b.status}">${b.status}</span></td>
      <td class="notes-cell" title="${escHtml(b.notes)}">${escHtml(b.notes)}</td>
    </tr>`).join('');
}

function renderStatusCards(area) {
  const unrestEl = document.getElementById('unrest-status');
  const unrestNotes = document.getElementById('unrest-notes');
  const energyEl = document.getElementById('energy-status');
  const energyNotes = document.getElementById('energy-notes');

  if (unrestEl && area.domestic_unrest) {
    const u = area.domestic_unrest;
    unrestEl.innerHTML = `<span class="status-pill status-${u.status}">${u.status}</span>`;
    if (unrestNotes) unrestNotes.textContent = u.notes;
  }
  if (energyEl && area.energy_infra) {
    const e = area.energy_infra;
    energyEl.innerHTML = `<span class="status-pill status-${e.status}">${e.status}</span>`;
    if (energyNotes) energyNotes.textContent = e.notes;
  }
  const waterCard  = document.getElementById('water-card');
  const waterEl    = document.getElementById('water-status');
  const waterNotes = document.getElementById('water-notes');
  if (waterEl && area.water_infra) {
    if (waterCard) waterCard.style.display = '';
    const w = area.water_infra;
    waterEl.innerHTML = `<span class="status-pill status-${w.status}">${w.status}</span>`;
    if (waterNotes) waterNotes.textContent = w.notes;
  }
}

// ── Evac Routes ───────────────────────────────────────────────────────────────
function renderEvacRoutes(area) {
  const grid = document.getElementById('evac-routes-grid');
  const opsBadge = document.getElementById('airports-ops-badge');
  if (!grid) return;

  const routes = area.evac_routes || [];
  const airports = area.airports || [];

  // Count operational airports for badge
  const opsCount = airports.filter(a =>
    !['CLOSED'].includes(a.status)).length;
  const totalAp = airports.length;
  if (opsBadge) opsBadge.textContent = `${opsCount} of ${totalAp} airports operational`;

  if (!routes.length) {
    grid.innerHTML = '<div class="feed-empty">No ground routes on record</div>';
    return;
  }

  // Build a lookup from border name → status using area.borders
  const borderMap = {};
  (area.borders || []).forEach(b => { borderMap[b.name] = b.status; });

  grid.innerHTML = routes.map(route => {
    const riskCls = RISK_CLASS[route.risk] || 'risk-moderate';
    const dstStatus = getDstAirportStatus(route.destination_airport_iata, area);
    const dstStatusHtml = dstStatus
      ? `<span class="status-pill status-${dstStatus}">${dstStatus}</span>`
      : `<span class="status-pill status-UNKNOWN">UNKNOWN</span>`;

    // Crossing statuses
    const crossingRows = (route.crossings || []).map(name => {
      const st = borderMap[name];
      if (!st) return '';
      return `<div class="evac-crossing-row">
        <span class="evac-crossing-name">${escHtml(name)}</span>
        <span class="status-pill status-${st}">${st}</span>
      </div>`;
    }).join('');

    // Warning if destination airport is closed
    const dstWarning = (dstStatus === 'CLOSED')
      ? `<div class="evac-warning">Destination airport CLOSED as of last update</div>`
      : '';

    const destLine = route.destination_airport_iata
      ? `${route.destination_airport_iata} · ${route.destination_airport_name}`
      : route.destination_airport_name;

    return `
      <div class="evac-card">
        <div class="evac-card-header">
          <div class="evac-label">${escHtml(route.label)}</div>
          <span class="risk-pill ${riskCls}">${route.risk}</span>
        </div>
        <div class="evac-drive-time">${escHtml(route.drive_time)}</div>
        <div class="evac-via">Via: ${escHtml(route.via)}</div>
        <div class="evac-section-label">Border crossings</div>
        <div class="evac-crossings">${crossingRows || '<span style="color:var(--text-dim)">—</span>'}</div>
        <div class="evac-section-label">Destination airport</div>
        <div class="evac-dest-row">
          <span class="evac-dest-name">${escHtml(destLine)}</span>
          ${dstStatusHtml}
        </div>
        ${dstWarning}
        ${route.notes ? `<div class="evac-notes">${escHtml(route.notes)}</div>` : ''}
      </div>`;
  }).join('');
}

/**
 * Best-effort: look up destination airport status from area airports first,
 * then fall back to a known static table for cross-country destinations.
 */
function getDstAirportStatus(iata, area) {
  if (!iata) return null;
  // Check area's own airports first
  const own = (area.airports || []).find(a => a.iata === iata);
  if (own) return own.status;
  // Known cross-area statuses (populated from data as of last update)
  const crossAreaStatus = {
    'MCT': 'OPEN',
    'AMM': 'OPEN',
    'KWI': 'OPEN',
    'DMM': 'DEGRADED',
    'RUH': 'WATCH',
  };
  return crossAreaStatus[iata] || 'UNKNOWN';
}

// ══════════════════════════════════════════════════════════════════════════════
//  COMMENT WIDGET (all pages)
// ══════════════════════════════════════════════════════════════════════════════
function initCommentWidget() {
  const form = document.getElementById('comment-form');
  const statusEl = document.getElementById('comment-status');
  if (!form) return;

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const body = {
      page:    fd.get('page') || PAGE,
      area:    fd.get('area') || AREA_SLUG,
      name:    fd.get('name') || '',
      contact: fd.get('contact') || '',
      text:    fd.get('text') || '',
    };
    if (!body.text.trim()) return;

    const btn = form.querySelector('button[type=submit]');
    btn.disabled = true;
    btn.textContent = 'Sending…';

    try {
      const res = await fetch('/api/comment', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      form.querySelector('textarea').value = '';
      if (statusEl) {
        statusEl.textContent = 'Submitted.';
        statusEl.className = 'comment-status ok';
        setTimeout(() => { statusEl.textContent = ''; statusEl.className = 'comment-status'; }, 4000);
      }
    } catch (err) {
      if (statusEl) {
        statusEl.textContent = 'Submit failed — ' + err.message;
        statusEl.className = 'comment-status error';
      }
    } finally {
      btn.disabled = false;
      btn.textContent = 'Submit to Bayo';
    }
  });
}

// ── Utilities ────────────────────────────────────────────────────────────────
function hideLoading() {
  const el = document.getElementById('loading');
  if (el) el.classList.add('hidden');
}

function updateRefreshLabel(serverTime) {
  const el = document.getElementById('page-refresh');
  if (!el || !serverTime) return;
  el.textContent = `Data as of: ${formatTs(serverTime)}`;
}

function formatTs(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    const dd = String(d.getUTCDate()).padStart(2, '0');
    const mo = d.toLocaleString('en-US', { month: 'short', timeZone: 'UTC' }).toUpperCase();
    const hh = String(d.getUTCHours()).padStart(2, '0');
    const mm = String(d.getUTCMinutes()).padStart(2, '0');
    return `${dd} ${mo} ${hh}:${mm}Z`;
  } catch { return iso; }
}

function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

let toastTimer = null;
function showToast(msg, isError = false) {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = msg;
  el.className = 'toast' + (isError ? ' error' : '');
  void el.offsetWidth;
  el.classList.add('show');
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 4000);
}

// ── State Dept Travel Advisories ──────────────────────────────────────────────
const ADVISORY_LEVEL_CLASS = {
  '1': 'adv-l1', '2': 'adv-l2', '3': 'adv-l3', '4': 'adv-l4',
};
const ADVISORY_LEVEL_LABEL = {
  'Level 1: Exercise Normal Precautions':   { short: 'L1', label: 'Normal Precautions' },
  'Level 2: Exercise Increased Caution':    { short: 'L2', label: 'Increased Caution' },
  'Level 3: Reconsider Travel':             { short: 'L3', label: 'Reconsider Travel' },
  'Level 4: Do Not Travel':                 { short: 'L4', label: 'Do Not Travel' },
};

// Landing page — horizontal strip of all relevant countries
function renderStateDeptStrip(stateDept) {
  const el = document.getElementById('state-dept-strip');
  const updEl = document.getElementById('state-dept-updated');
  if (!el) return;

  if (!stateDept || !stateDept.countries) {
    el.innerHTML = '<div class="feed-empty">Advisory data unavailable</div>';
    return;
  }

  if (updEl) {
    const ts = stateDept.fetched_utc ? formatTs(stateDept.fetched_utc) : '—';
    updEl.textContent = `Updated ${ts}`;
  }

  const countries = stateDept.countries;
  const ORDER = ['Iran','United Arab Emirates','Saudi Arabia','Bahrain','Oman','Qatar','Kuwait','Jordan','Iraq','Lebanon','Yemen'];
  const items = ORDER.filter(c => countries[c]).map(c => countries[c]);

  el.innerHTML = items.map(adv => {
    const lnum = (adv.level || '').match(/Level (\d)/)?.[1] || '?';
    const cls  = ADVISORY_LEVEL_CLASS[lnum] || 'adv-l1';
    const meta = ADVISORY_LEVEL_LABEL[adv.level] || { short: `L${lnum}`, label: adv.level };
    const date = adv.updated ? adv.updated.slice(0,10) : '';
    return `
      <a class="adv-card ${cls}" href="${escHtml(adv.url)}" target="_blank" rel="noopener">
        <div class="adv-level-badge">${meta.short}</div>
        <div class="adv-country">${escHtml(adv.country)}</div>
        <div class="adv-label">${escHtml(meta.label)}</div>
        <div class="adv-date">${date}</div>
      </a>`;
  }).join('');
}

// Country page — single advisory card
function renderStateDeptCountry(adv) {
  const el = document.getElementById('state-dept-country-card');
  if (!el) return;

  if (!adv) {
    el.innerHTML = '<div class="feed-empty">No State Dept advisory data for this country</div>';
    return;
  }

  const lnum = (adv.level || '').match(/Level (\d)/)?.[1] || '?';
  const cls  = ADVISORY_LEVEL_CLASS[lnum] || 'adv-l1';
  const meta = ADVISORY_LEVEL_LABEL[adv.level] || { short: `L${lnum}`, label: adv.level };
  const date = adv.updated ? adv.updated.slice(0, 10) : '';

  el.innerHTML = `
    <div class="adv-country-card ${cls}">
      <div class="adv-country-card-header">
        <span class="adv-level-badge-lg">${meta.short}</span>
        <div>
          <div class="adv-country-name">${escHtml(adv.country)}</div>
          <div class="adv-country-label">${escHtml(meta.label)}</div>
        </div>
        <div class="adv-country-date">Updated: ${date}</div>
      </div>
      <div class="adv-country-source">
        <a href="${escHtml(adv.url)}" target="_blank" rel="noopener">
          travel.state.gov ↗
        </a>
      </div>
    </div>`;
}

// ── Map overlay tooltips ───────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  const tooltip = document.getElementById('map-tooltip');
  const zones   = document.querySelectorAll('.overlay-zone');
  if (!tooltip || !zones.length) return;

  zones.forEach(zone => {
    const name = zone.dataset.name || zone.dataset.slug;

    zone.addEventListener('mouseenter', e => {
      // Show label text in SVG
      const lbl = zone.nextElementSibling;
      if (lbl && lbl.classList.contains('overlay-label')) lbl.classList.add('visible');
      // Tooltip
      tooltip.textContent = name;
      tooltip.style.display = 'block';
    });

    zone.addEventListener('mousemove', e => {
      const rect = zone.closest('.arcgis-map-container').getBoundingClientRect();
      tooltip.style.left = (e.clientX - rect.left + 12) + 'px';
      tooltip.style.top  = (e.clientY - rect.top  - 8)  + 'px';
    });

    zone.addEventListener('mouseleave', () => {
      const lbl = zone.nextElementSibling;
      if (lbl && lbl.classList.contains('overlay-label')) lbl.classList.remove('visible');
      tooltip.style.display = 'none';
    });
  });
});
