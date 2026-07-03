/* RF Line-of-Sight Planner
 *
 * Drop nodes on the map → compute an RF viewshed from terrain elevation
 * (AWS Terrain Tiles, terrarium encoding, proxied through /api/rf/tile/).
 *
 * Propagation model:
 *   - 4/3 effective earth radius (standard atmospheric refraction)
 *   - Radial sweep viewshed keeping the max terrain elevation angle
 *   - Fresnel test against the single dominant obstruction:
 *       clearance >= 0.6 * F1  → clear RF LOS   (green)
 *       clearance >= 0         → marginal        (yellow)
 *       else                   → terrain-blocked (unshaded)
 *   - Node-to-node link profiles with earth bulge + first Fresnel zone
 */
'use strict';

// ── Constants ────────────────────────────────────────────────────────────────
const EARTH_R   = 6371000;
const K_FACTOR  = 4 / 3;                 // effective earth radius factor
const RE        = EARTH_R * K_FACTOR;
const M_PER_DEG = 111320;                // meters per degree latitude (approx)
const FRESNEL_CLEAR = 0.6;               // fraction of F1 required for "clear"
const MAX_LINK_KM   = 80;                // don't evaluate links longer than this
const STORE_KEY     = 'rf-planner-state-v1';
const VIEW_KEY      = 'rf-planner-view-v1';

const STATUS_BLOCKED = 0, STATUS_MARGINAL = 1, STATUS_CLEAR = 2;

// ── Global state ─────────────────────────────────────────────────────────────
const settings = { freqMHz: 906.875, txH: 6, rxH: 2, radiusKm: 15 };
let nodes = [];          // {id, name, lat, lon, h, radiusKm, marker, overlay, circle, visible, groundElev}
let links = new Map();   // "idA|idB" -> {line, verdict, profile}
let nextId = 1;
let map;

// ── Elevation tiles (terrarium) ──────────────────────────────────────────────
const tileCache = new Map();   // "z/x/y" -> Promise<Float32Array|null>

function lonToTileX(lon, z) { return (lon + 180) / 360 * (1 << z); }
function latToTileY(lat, z) {
  const r = lat * Math.PI / 180;
  return (1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2 * (1 << z);
}

function fetchTile(z, x, y) {
  const n = 1 << z;
  if (y < 0 || y >= n) return Promise.resolve(null);
  x = ((x % n) + n) % n;
  const key = `${z}/${x}/${y}`;
  if (tileCache.has(key)) return tileCache.get(key);

  const p = fetch(`/api/rf/tile/${z}/${x}/${y}.png`)
    .then(r => { if (!r.ok) throw new Error(`tile ${key}: ${r.status}`); return r.blob(); })
    .then(b => createImageBitmap(b))
    .then(img => {
      const cv = document.createElement('canvas');
      cv.width = cv.height = 256;
      const ctx = cv.getContext('2d', { willReadFrequently: true });
      ctx.drawImage(img, 0, 0);
      const px = ctx.getImageData(0, 0, 256, 256).data;
      const out = new Float32Array(256 * 256);
      for (let i = 0, j = 0; i < out.length; i++, j += 4) {
        // terrarium: elev = (R*256 + G + B/256) - 32768
        out[i] = px[j] * 256 + px[j + 1] + px[j + 2] / 256 - 32768;
      }
      return out;
    })
    .catch(() => null);
  tileCache.set(key, p);
  return p;
}

/* Prefetch all tiles covering a lat/lon bounding box; resolves to a sampler:
 * sample(lat, lon) -> elevation in meters (sea clamped to 0, missing -> 0). */
async function buildSampler(latMin, latMax, lonMin, lonMax, zoom, onProgress) {
  const x0 = Math.floor(lonToTileX(lonMin, zoom)), x1 = Math.floor(lonToTileX(lonMax, zoom));
  const y0 = Math.floor(latToTileY(latMax, zoom)), y1 = Math.floor(latToTileY(latMin, zoom));
  const wanted = [];
  for (let x = x0; x <= x1; x++)
    for (let y = y0; y <= y1; y++) wanted.push([x, y]);

  const tiles = new Map();
  let done = 0;
  const CONCURRENCY = 12;
  const queue = wanted.slice();
  async function worker() {
    while (queue.length) {
      const [x, y] = queue.pop();
      tiles.set(`${x}/${y}`, await fetchTile(zoom, x, y));
      done++;
      if (onProgress) onProgress(done, wanted.length);
    }
  }
  await Promise.all(Array.from({ length: Math.min(CONCURRENCY, wanted.length) }, worker));

  return function sample(lat, lon) {
    const fx = lonToTileX(lon, zoom), fy = latToTileY(lat, zoom);
    const tx = Math.floor(fx), ty = Math.floor(fy);
    const data = tiles.get(`${tx}/${ty}`);
    if (!data) return 0;
    // bilinear within the tile (clamped at edges)
    let px = (fx - tx) * 256 - 0.5, py = (fy - ty) * 256 - 0.5;
    px = Math.min(254.999, Math.max(0, px));
    py = Math.min(254.999, Math.max(0, py));
    const ix = Math.floor(px), iy = Math.floor(py);
    const dx = px - ix, dy = py - iy;
    const i00 = iy * 256 + ix;
    const e = data[i00] * (1 - dx) * (1 - dy) + data[i00 + 1] * dx * (1 - dy)
            + data[i00 + 256] * (1 - dx) * dy + data[i00 + 257] * dx * dy;
    // terrarium includes bathymetry; RF over water reflects off the surface,
    // so clamp to sea level
    return Math.max(0, e);
  };
}

function zoomForRadius(radiusM) {
  if (radiusM <= 5000)  return 13;
  if (radiusM <= 16000) return 12;
  if (radiusM <= 40000) return 11;
  return 10;
}

function metersPerPixel(zoom, lat) {
  return 156543.03392 * Math.cos(lat * Math.PI / 180) / (1 << zoom);
}

// ── Viewshed computation ─────────────────────────────────────────────────────
async function computeViewshed(node, onProgress) {
  const lat0 = node.lat, lon0 = node.lon;
  const radius = node.radiusKm * 1000;
  const zoom = zoomForRadius(radius);
  const cosLat = Math.cos(lat0 * Math.PI / 180);
  const dLat = radius / M_PER_DEG;
  const dLon = radius / (M_PER_DEG * cosLat);
  const pad = 1.05;

  const sample = await buildSampler(
    lat0 - dLat * pad, lat0 + dLat * pad,
    lon0 - dLon * pad, lon0 + dLon * pad,
    zoom, onProgress
  );

  const step  = Math.max(20, metersPerPixel(zoom, lat0));
  const nBins = Math.ceil(radius / step);
  const nAz   = Math.min(1440, Math.max(360, Math.ceil(Math.PI * radius / step)));
  const grid  = new Uint8Array(nAz * nBins);

  const groundElev = sample(lat0, lon0);
  node.groundElev = groundElev;
  const txASL = groundElev + node.h;
  const rxH = settings.rxH;
  const lambda = 299.792458 / settings.freqMHz;   // wavelength in meters

  for (let a = 0; a < nAz; a++) {
    const az = a / nAz * 2 * Math.PI;
    const sinAz = Math.sin(az), cosAz = Math.cos(az);
    let maxAng = -Infinity;   // steepest terrain elevation angle so far
    let dObs = 0;             // distance of that dominant obstruction

    for (let j = 1; j <= nBins; j++) {
      const d = j * step;
      const lat = lat0 + (d * cosAz) / M_PER_DEG;
      const lon = lon0 + (d * sinAz) / (M_PER_DEG * cosLat);
      const e = sample(lat, lon);
      const hg = e - d * d / (2 * RE);          // curvature-corrected ground
      const angRx = (hg + rxH - txASL) / d;     // angle to a receiver antenna
      const angGround = (hg - txASL) / d;       // angle to bare terrain

      let status = STATUS_BLOCKED;
      if (angRx >= maxAng) {
        if (dObs === 0) {
          status = STATUS_CLEAR;                // nothing between us yet
        } else {
          // ray height above the dominant obstruction vs. Fresnel radius there
          const clearance = (angRx - maxAng) * dObs;
          const f1 = Math.sqrt(lambda * dObs * (d - dObs) / d);
          status = clearance >= FRESNEL_CLEAR * f1 ? STATUS_CLEAR : STATUS_MARGINAL;
        }
      }
      grid[a * nBins + j - 1] = status;

      if (angGround > maxAng) { maxAng = angGround; dObs = d; }
    }
  }

  // Rasterize the polar grid onto a square canvas (local equirectangular)
  const S = 1024;
  const cv = document.createElement('canvas');
  cv.width = cv.height = S;
  const ctx = cv.getContext('2d');
  const img = ctx.createImageData(S, S);
  const px = img.data;
  const TWO_PI = 2 * Math.PI;

  for (let py = 0; py < S; py++) {
    const dy = (1 - 2 * py / (S - 1)) * radius;   // north positive
    for (let pxi = 0; pxi < S; pxi++) {
      const dx = (2 * pxi / (S - 1) - 1) * radius; // east positive
      const r = Math.hypot(dx, dy);
      if (r > radius || r < step * 0.5) continue;
      let az = Math.atan2(dx, dy);
      if (az < 0) az += TWO_PI;
      const a = Math.round(az / TWO_PI * nAz) % nAz;
      const j = Math.min(nBins - 1, Math.max(0, Math.round(r / step) - 1));
      const s = grid[a * nBins + j];
      if (s === STATUS_BLOCKED) continue;
      const o = (py * S + pxi) * 4;
      if (s === STATUS_CLEAR) { px[o] = 46;  px[o + 1] = 204; px[o + 2] = 90; }
      else                    { px[o] = 240; px[o + 1] = 200; px[o + 2] = 40; }
      px[o + 3] = 110;
    }
  }
  ctx.putImageData(img, 0, 0);

  return {
    url: cv.toDataURL('image/png'),
    bounds: [[lat0 - dLat, lon0 - dLon], [lat0 + dLat, lon0 + dLon]],
  };
}

// ── Link (point-to-point) evaluation ─────────────────────────────────────────
function haversine(lat1, lon1, lat2, lon2) {
  const r = Math.PI / 180;
  const a = Math.sin((lat2 - lat1) * r / 2) ** 2 +
            Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin((lon2 - lon1) * r / 2) ** 2;
  return 2 * EARTH_R * Math.asin(Math.sqrt(a));
}

async function computeLinkProfile(na, nb) {
  const D = haversine(na.lat, na.lon, nb.lat, nb.lon);
  const zoom = zoomForRadius(D / 2);
  const latMin = Math.min(na.lat, nb.lat), latMax = Math.max(na.lat, nb.lat);
  const lonMin = Math.min(na.lon, nb.lon), lonMax = Math.max(na.lon, nb.lon);
  const padLat = 0.02, padLon = 0.02;
  const sample = await buildSampler(latMin - padLat, latMax + padLat,
                                    lonMin - padLon, lonMax + padLon, zoom);

  const N = Math.min(1024, Math.max(128, Math.ceil(D / metersPerPixel(zoom, na.lat))));
  const lambda = 299.792458 / settings.freqMHz;
  const txASL = sample(na.lat, na.lon) + na.h;
  const rxASL = sample(nb.lat, nb.lon) + nb.h;

  const pts = [];       // {d, terrain (with bulge), los, f1}
  let minRatio = Infinity;   // min clearance / F1 along the path
  for (let i = 0; i <= N; i++) {
    const t = i / N;
    const d1 = t * D, d2 = D - d1;
    const lat = na.lat + (nb.lat - na.lat) * t;
    const lon = na.lon + (nb.lon - na.lon) * t;
    const bulge = d1 * d2 / (2 * RE);
    const terrain = sample(lat, lon) + bulge;
    const los = txASL + (rxASL - txASL) * t;
    const f1 = i === 0 || i === N ? 0 : Math.sqrt(lambda * d1 * d2 / D);
    pts.push({ d: d1, terrain, los, f1 });
    if (f1 > 0) minRatio = Math.min(minRatio, (los - terrain) / f1);
  }

  let verdict;
  if (minRatio >= FRESNEL_CLEAR) verdict = 'clear';
  else if (minRatio >= 0)        verdict = 'marginal';
  else                           verdict = 'blocked';

  return { D, pts, verdict, minRatio, txASL, rxASL, a: na, b: nb };
}

// ── Profile chart ────────────────────────────────────────────────────────────
function drawProfile(profile) {
  const panel = document.getElementById('rf-profile');
  const canvas = document.getElementById('rf-profile-canvas');
  panel.hidden = false;
  canvas.width = canvas.clientWidth * (window.devicePixelRatio || 1) || 1200;
  canvas.height = 260 * (window.devicePixelRatio || 1);
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);

  const { D, pts, verdict, minRatio, a, b } = profile;
  const padL = 46 * (W / 1200), padR = 14, padT = 14, padB = 26;

  let hMin = Infinity, hMax = -Infinity;
  for (const p of pts) {
    hMin = Math.min(hMin, p.terrain, p.los - p.f1);
    hMax = Math.max(hMax, p.terrain, p.los + p.f1);
  }
  const span = Math.max(20, hMax - hMin);
  hMin -= span * 0.08; hMax += span * 0.08;

  const X = d => padL + (d / D) * (W - padL - padR);
  const Y = h => H - padB - ((h - hMin) / (hMax - hMin)) * (H - padT - padB);

  // grid + axis labels
  ctx.strokeStyle = '#21262d'; ctx.fillStyle = '#8b949e';
  ctx.font = `${11 * (W / 1200) * 1.6}px monospace`;
  ctx.lineWidth = 1;
  for (let g = 0; g <= 4; g++) {
    const h = hMin + (hMax - hMin) * g / 4;
    ctx.beginPath(); ctx.moveTo(padL, Y(h)); ctx.lineTo(W - padR, Y(h)); ctx.stroke();
    ctx.fillText(`${Math.round(h)} m`, 4, Y(h) + 4);
  }
  for (let g = 0; g <= 5; g++) {
    const d = D * g / 5;
    ctx.fillText(`${(d / 1000).toFixed(1)} km`, X(d) - 14, H - 8);
  }

  // Fresnel zone (F1 ellipse around LOS)
  ctx.beginPath();
  for (const p of pts) ctx.lineTo(X(p.d), Y(p.los + p.f1));
  for (let i = pts.length - 1; i >= 0; i--) ctx.lineTo(X(pts[i].d), Y(pts[i].los - pts[i].f1));
  ctx.closePath();
  ctx.fillStyle = 'rgba(88, 166, 255, 0.13)';
  ctx.fill();
  // 60% keep-out
  ctx.beginPath();
  for (const p of pts) ctx.lineTo(X(p.d), Y(p.los + p.f1 * FRESNEL_CLEAR));
  for (let i = pts.length - 1; i >= 0; i--) ctx.lineTo(X(pts[i].d), Y(pts[i].los - pts[i].f1 * FRESNEL_CLEAR));
  ctx.closePath();
  ctx.fillStyle = 'rgba(88, 166, 255, 0.16)';
  ctx.fill();

  // terrain (with earth bulge)
  ctx.beginPath();
  ctx.moveTo(X(0), Y(hMin));
  for (const p of pts) ctx.lineTo(X(p.d), Y(p.terrain));
  ctx.lineTo(X(D), Y(hMin));
  ctx.closePath();
  ctx.fillStyle = 'rgba(110, 90, 50, 0.55)';
  ctx.fill();
  ctx.strokeStyle = '#a07a3a'; ctx.lineWidth = 1.5; ctx.stroke();

  // LOS ray
  const color = verdict === 'clear' ? '#2ecc5a' : verdict === 'marginal' ? '#f0c828' : '#f85149';
  ctx.beginPath();
  ctx.moveTo(X(0), Y(pts[0].los));
  ctx.lineTo(X(D), Y(pts[pts.length - 1].los));
  ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke();

  // antenna masts
  ctx.strokeStyle = '#f0a500'; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(X(0), Y(pts[0].terrain - pts[0].f1 * 0)); ctx.lineTo(X(0), Y(pts[0].los)); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(X(D), Y(pts[pts.length - 1].terrain)); ctx.lineTo(X(D), Y(pts[pts.length - 1].los)); ctx.stroke();

  const title = document.getElementById('rf-profile-title');
  title.textContent = `${a.name} ⇄ ${b.name} — ${(D / 1000).toFixed(2)} km`;
  const verdictEl = document.getElementById('rf-profile-verdict');
  const pctF1 = Number.isFinite(minRatio) ? `${Math.round(minRatio * 100)}% of F1 worst-case clearance` : '';
  const label = verdict === 'clear' ? '✔ CLEAR RF PATH' : verdict === 'marginal' ? '⚠ MARGINAL (Fresnel intrusion)' : '✘ TERRAIN BLOCKED';
  verdictEl.textContent = `${label} · ${pctF1} · ${settings.freqMHz} MHz`;
  verdictEl.className = `verdict-${verdict}`;
}

// ── Map + UI ─────────────────────────────────────────────────────────────────
function setStatus(msg) {
  const el = document.getElementById('rf-status');
  if (!msg) { el.hidden = true; return; }
  el.hidden = false;
  el.textContent = msg;
}

function nodeIcon() {
  return L.divIcon({ className: 'rf-node-marker', iconSize: [16, 16], iconAnchor: [8, 8] });
}

function saveState() {
  const data = {
    settings,
    nodes: nodes.map(n => ({ id: n.id, name: n.name, lat: n.lat, lon: n.lon, h: n.h, radiusKm: n.radiusKm })),
  };
  localStorage.setItem(STORE_KEY, JSON.stringify(data));
}

function addNode(lat, lon, opts = {}) {
  const node = {
    id: opts.id || nextId,
    name: opts.name || `Node ${nextId}`,
    lat, lon,
    h: opts.h != null ? opts.h : settings.txH,
    radiusKm: opts.radiusKm != null ? opts.radiusKm : settings.radiusKm,
    marker: null, overlay: null, circle: null,
    visible: true, groundElev: null, computing: false,
  };
  nextId = Math.max(nextId, node.id) + 1;

  node.marker = L.marker([lat, lon], { icon: nodeIcon(), draggable: true, title: node.name })
    .addTo(map)
    .on('dragend', () => {
      const p = node.marker.getLatLng();
      node.lat = p.lat; node.lon = p.lng;
      saveState();
      renderNodeList();
      recomputeNode(node);
    })
    .bindTooltip(() => `${node.name} · ant ${node.h} m`, { direction: 'top' });

  nodes.push(node);
  saveState();
  renderNodeList();
  recomputeNode(node);
  return node;
}

function removeNode(node) {
  if (node.marker) map.removeLayer(node.marker);
  if (node.overlay) map.removeLayer(node.overlay);
  if (node.circle) map.removeLayer(node.circle);
  nodes = nodes.filter(n => n !== node);
  for (const [key, link] of [...links]) {
    if (key.split('|').map(Number).includes(node.id)) {
      if (link.line) map.removeLayer(link.line);
      links.delete(key);
    }
  }
  saveState();
  renderNodeList();
}

// serialize heavy computations so we don't saturate the tile proxy / CPU
let computeChain = Promise.resolve();

function recomputeNode(node) {
  node.computing = true;
  renderNodeList();
  computeChain = computeChain.then(async () => {
    if (!nodes.includes(node)) return;   // deleted while queued
    try {
      setStatus(`Computing viewshed for ${node.name}…`);
      const res = await computeViewshed(node, (done, total) => {
        setStatus(`${node.name}: terrain tiles ${done}/${total}…`);
      });
      if (!nodes.includes(node)) return;
      if (node.overlay) map.removeLayer(node.overlay);
      if (node.circle) map.removeLayer(node.circle);
      node.overlay = L.imageOverlay(res.url, res.bounds, { opacity: 0.85, interactive: false });
      node.circle = L.circle([node.lat, node.lon], {
        radius: node.radiusKm * 1000, color: '#f0a500', weight: 1,
        fill: false, dashArray: '4 6', interactive: false,
      });
      if (node.visible) { node.overlay.addTo(map); node.circle.addTo(map); }
    } finally {
      node.computing = false;
      setStatus('');
      renderNodeList();
    }
    await updateLinksFor(node);
  }).catch(err => {
    console.warn('viewshed compute failed', err);
    setStatus('');
  });
}

function linkKey(a, b) { return a.id < b.id ? `${a.id}|${b.id}` : `${b.id}|${a.id}`; }

async function updateLinksFor(node) {
  for (const other of nodes) {
    if (other === node) continue;
    const key = linkKey(node, other);
    const old = links.get(key);
    if (old && old.line) map.removeLayer(old.line);
    links.delete(key);

    const D = haversine(node.lat, node.lon, other.lat, other.lon);
    if (D > MAX_LINK_KM * 1000 || D < 10) continue;

    try {
      const profile = await computeLinkProfile(node, other);
      const color = profile.verdict === 'clear' ? '#2ecc5a'
                  : profile.verdict === 'marginal' ? '#f0c828' : '#f85149';
      const line = L.polyline([[node.lat, node.lon], [other.lat, other.lon]], {
        color, weight: 3, opacity: 0.9,
        dashArray: profile.verdict === 'blocked' ? '4 8' : null,
        bubblingMouseEvents: false,   // clicking the link must not drop a node
      }).addTo(map)
        .bindTooltip(`${node.name} ⇄ ${other.name} · ${(D / 1000).toFixed(1)} km · ${profile.verdict.toUpperCase()} — click for profile`)
        .on('click', () => drawProfile(profile));
      links.set(key, { line, verdict: profile.verdict, profile });
    } catch (e) {
      console.warn('link eval failed', e);
    }
  }
}

// ── Sidebar node list ────────────────────────────────────────────────────────
function renderNodeList() {
  const wrap = document.getElementById('rf-node-list');
  const count = document.getElementById('rf-node-count');
  count.textContent = nodes.length ? `(${nodes.length})` : '';
  wrap.innerHTML = '';
  if (!nodes.length) {
    wrap.innerHTML = '<div class="rf-empty">No nodes yet — click the map to place one.</div>';
    return;
  }

  for (const node of nodes) {
    const el = document.createElement('div');
    el.className = 'rf-node';
    const elev = node.groundElev != null ? `${Math.round(node.groundElev)} m ASL` : '…';
    el.innerHTML = `
      <div class="rf-node-title">
        <span class="rf-node-dot"></span>
        <input type="text" data-f="name" value="${escapeHtml(node.name)}" />
      </div>
      <div class="rf-node-grid">
        <label><span>Antenna AGL (m)</span><input type="number" data-f="h" min="0.5" step="0.5" value="${node.h}" /></label>
        <label><span>Radius (km)</span><input type="number" data-f="radiusKm" min="1" max="80" step="1" value="${node.radiusKm}" /></label>
      </div>
      <div class="rf-node-meta">${node.lat.toFixed(5)}, ${node.lon.toFixed(5)} · ground ${elev}</div>
      <div class="rf-node-actions">
        <button class="rf-btn rf-btn-small" data-a="zoom">Zoom</button>
        <button class="rf-btn rf-btn-small" data-a="toggle">${node.visible ? 'Hide shed' : 'Show shed'}</button>
        <button class="rf-btn rf-btn-small" data-a="recompute">Recompute</button>
        <button class="rf-btn rf-btn-small rf-btn-danger" data-a="delete">Delete</button>
      </div>
      ${node.computing ? '<div class="rf-node-status">⏳ computing viewshed…</div>' : ''}
    `;

    el.querySelector('[data-f="name"]').addEventListener('change', ev => {
      node.name = ev.target.value.trim() || node.name;
      node.marker.setTooltipContent(`${node.name} · ant ${node.h} m`);
      saveState();
    });
    el.querySelector('[data-f="h"]').addEventListener('change', ev => {
      const v = parseFloat(ev.target.value);
      if (v > 0) { node.h = v; saveState(); recomputeNode(node); }
    });
    el.querySelector('[data-f="radiusKm"]').addEventListener('change', ev => {
      const v = parseFloat(ev.target.value);
      if (v >= 1 && v <= 80) { node.radiusKm = v; saveState(); recomputeNode(node); }
    });
    el.querySelector('[data-a="zoom"]').addEventListener('click', () => {
      map.setView([node.lat, node.lon], Math.max(map.getZoom(), 12));
    });
    el.querySelector('[data-a="toggle"]').addEventListener('click', () => {
      node.visible = !node.visible;
      if (node.overlay) node.visible ? node.overlay.addTo(map) : map.removeLayer(node.overlay);
      if (node.circle)  node.visible ? node.circle.addTo(map)  : map.removeLayer(node.circle);
      renderNodeList();
    });
    el.querySelector('[data-a="recompute"]').addEventListener('click', () => recomputeNode(node));
    el.querySelector('[data-a="delete"]').addEventListener('click', () => removeNode(node));

    wrap.appendChild(el);
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

// ── Global settings handlers ─────────────────────────────────────────────────
let globalRecomputeTimer = null;
function recomputeAll() {
  clearTimeout(globalRecomputeTimer);
  globalRecomputeTimer = setTimeout(() => {
    for (const node of nodes) recomputeNode(node);
  }, 500);
}

function bindSettings() {
  const freq = document.getElementById('rf-freq');
  const txh = document.getElementById('rf-txh');
  const rxh = document.getElementById('rf-rxh');
  const rad = document.getElementById('rf-radius');

  freq.value = String(settings.freqMHz);
  if (freq.value !== String(settings.freqMHz)) {
    freq.value = '906.875';
    settings.freqMHz = 906.875;
  }
  txh.value = settings.txH;
  rxh.value = settings.rxH;
  rad.value = settings.radiusKm;

  freq.addEventListener('change', () => {
    settings.freqMHz = parseFloat(freq.value);
    saveState();
    recomputeAll();
  });
  txh.addEventListener('change', () => {
    const v = parseFloat(txh.value);
    if (v > 0) { settings.txH = v; saveState(); }   // applies to new nodes
  });
  rxh.addEventListener('change', () => {
    const v = parseFloat(rxh.value);
    if (v > 0) { settings.rxH = v; saveState(); recomputeAll(); }
  });
  rad.addEventListener('change', () => {
    const v = parseFloat(rad.value);
    if (v >= 1 && v <= 80) { settings.radiusKm = v; saveState(); }  // applies to new nodes
  });

  document.getElementById('rf-clear').addEventListener('click', () => {
    if (!nodes.length || !confirm('Remove all nodes and viewsheds?')) return;
    for (const node of [...nodes]) removeNode(node);
  });

  document.getElementById('rf-profile-close').addEventListener('click', () => {
    document.getElementById('rf-profile').hidden = true;
    map.invalidateSize();
  });
}

// ── Init ─────────────────────────────────────────────────────────────────────
function loadState() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch { return null; }
}

function init() {
  const saved = loadState();
  if (saved && saved.settings) Object.assign(settings, saved.settings);

  let view = { center: [25.6, 52.5], zoom: 7 };   // Gulf AOR default
  try {
    const v = JSON.parse(localStorage.getItem(VIEW_KEY));
    if (v && v.center) view = v;
  } catch { /* ignore */ }

  map = L.map('rf-map', { zoomControl: true }).setView(view.center, view.zoom);

  const osm = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, attribution: '&copy; OpenStreetMap contributors',
  });
  const topo = L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
    maxZoom: 17, attribution: '&copy; OpenStreetMap, SRTM — © OpenTopoMap (CC-BY-SA)',
  });
  const sat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 19, attribution: 'Tiles &copy; Esri',
  });
  topo.addTo(map);
  L.control.layers({ 'Topo': topo, 'OSM': osm, 'Satellite': sat }).addTo(map);
  L.control.scale({ imperial: true }).addTo(map);

  map.on('moveend', () => {
    const c = map.getCenter();
    localStorage.setItem(VIEW_KEY, JSON.stringify({ center: [c.lat, c.lng], zoom: map.getZoom() }));
  });

  map.on('click', ev => {
    if (!document.getElementById('rf-dropmode').checked) return;
    addNode(ev.latlng.lat, ev.latlng.lng);
  });

  bindSettings();
  renderNodeList();

  // restore saved nodes
  if (saved && Array.isArray(saved.nodes)) {
    for (const n of saved.nodes) {
      if (typeof n.lat === 'number' && typeof n.lon === 'number') {
        addNode(n.lat, n.lon, n);
      }
    }
  }
}

document.addEventListener('DOMContentLoaded', init);
