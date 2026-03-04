/* Gulf AOR Travel — travel.js */
'use strict';

let STATE = { airports: [], borders: [] };
let SCOPE = 'macro';

document.addEventListener('DOMContentLoaded', () => {
  startClock();
  wireScopeButtons();
  loadTravelData();
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

function wireScopeButtons() {
  document.querySelectorAll('.seg-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.seg-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      SCOPE = btn.dataset.scope;
      render();
    });
  });
}

async function loadTravelData() {
  try {
    const res = await fetch('/api/data');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    STATE.airports = data.airports || [];
    STATE.borders  = data.borders || [];

    document.getElementById('loading').classList.add('hidden');
    document.getElementById('last-updated').innerHTML =
      `LAST UPDATED <strong>${new Date().toUTCString().replace('GMT','Z')}</strong>`;

    render();
  } catch (e) {
    showToast('Failed to load travel data: ' + e.message, true);
    document.getElementById('loading').classList.add('hidden');
  }
}

function render() {
  renderAirports();
  renderBorders();
}

function renderAirports() {
  const grid = document.getElementById('airports-grid');
  const badge = document.getElementById('air-badge');

  const airports = STATE.airports.filter(a => {
    if (SCOPE === 'macro') return true;
    const c = (a.country || '').toLowerCase();
    if (SCOPE === 'uae') return c.includes('uae');
    if (SCOPE === 'bahrain') return c.includes('bahrain');
    if (SCOPE === 'qatar') return c.includes('qatar');
    if (SCOPE === 'saudi') return c.includes('saudi');
    if (SCOPE === 'oman') return c.includes('oman');
    return true;
  });

  badge.textContent = `${airports.length} Airports`;

  grid.innerHTML = '';
  airports.forEach(a => {
    const card = document.createElement('div');
    card.className = 'airport-card';
    const status = (a.status || 'UNKNOWN').toUpperCase();
    const statusCls = status === 'OPEN' ? 'open' : (status === 'CLOSED' ? 'closed' : 'obstructed');
    card.innerHTML = `
      <div class="airport-title">${esc(a.code || '')} <span class="airport-name">${esc(a.name || '')}</span></div>
      <div class="airport-meta">${esc(a.country || '')}</div>
      <div class="airport-status ${statusCls}">${status}</div>
      <div class="airport-notes">${esc(a.notes || '')}</div>
    `;
    grid.appendChild(card);
  });
}

function renderBorders() {
  const tbody = document.getElementById('borders-tbody');

  const borders = STATE.borders.filter(b => {
    if (SCOPE === 'macro') return true;
    const s = `${b.country_a || ''} ${b.country_b || ''} ${b.name || ''}`.toLowerCase();
    if (SCOPE === 'uae') return s.includes('uae');
    if (SCOPE === 'bahrain') return s.includes('bahrain');
    if (SCOPE === 'qatar') return s.includes('qatar');
    if (SCOPE === 'saudi') return s.includes('saudi');
    if (SCOPE === 'oman') return s.includes('oman');
    return true;
  });

  tbody.innerHTML = '';
  borders.forEach(b => {
    const tr = document.createElement('tr');
    const status = (b.status || 'UNKNOWN').toUpperCase();
    tr.innerHTML = `
      <td style="font-weight:500;">${esc(b.name || '')}</td>
      <td><span class="status-pill status-${esc(status)}">${esc(status)}</span></td>
      <td class="notes-cell">${esc(b.notes || '')}</td>
    `;
    tbody.appendChild(tr);
  });
}

function esc(s) {
  return String(s || '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','\'':'&#39;','"':'&quot;'}[c]));
}

function showToast(msg, isErr=false) {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.toggle('error', !!isErr);
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 4200);
}
