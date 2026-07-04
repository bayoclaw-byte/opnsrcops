/* EUD onboarding page: generate TAK enrollment package + kit-card QRs. */
'use strict';

let obConfig = null;

function qrInto(el, text) {
  el.innerHTML = '';
  // qrcode-generator: type 0 = auto-size, M error correction
  const qr = qrcode(0, 'M');
  qr.addData(text);
  qr.make();
  el.innerHTML = qr.createSvgTag({ scalable: true, margin: 2 });
}

/* Escape special chars for the WIFI: QR payload (\ ; , " :) */
function wifiEscape(s) {
  return String(s).replace(/([\\;,":])/g, '\\$1');
}

async function loadConfig() {
  const warn = document.getElementById('ob-config-warn');
  const btn = document.getElementById('ob-generate');
  try {
    obConfig = await (await fetch('/api/onboard/config')).json();
  } catch {
    warn.hidden = false;
    warn.textContent = 'Could not reach /api/onboard/config';
    btn.disabled = true;
    return;
  }
  const notes = [];
  if (!obConfig.configured) {
    notes.push(`TAK enrollment disabled — set ${obConfig.missing.join(', ')} in the server environment.`);
    btn.disabled = true;
  } else if (!obConfig.can_mint) {
    notes.push('TAK_MAKECERT not set: certs must already exist in TAK_CERT_DIR '
      + '(run makeCert.sh client <name> on the TAK host beforehand).');
  }
  if (!obConfig.mesh_url) notes.push('MESH_CHANNEL_URL not set — Meshtastic QR will be omitted from kit cards.');
  if (!obConfig.wifi_ssid) notes.push('HAVEN_WIFI_SSID/PSK not set — WiFi QR will be omitted from kit cards.');
  if (notes.length) {
    warn.hidden = false;
    warn.innerHTML = notes.map(n => '• ' + n).join('<br>');
  }
}

async function generate(ev) {
  ev.preventDefault();
  const callsign = document.getElementById('ob-callsign').value.trim();
  const status = document.getElementById('ob-status');
  const btn = document.getElementById('ob-generate');
  if (!callsign) return;
  btn.disabled = true;
  status.textContent = 'Generating enrollment package…';
  try {
    const r = await fetch('/api/onboard/package', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ callsign }),
    });
    const res = await r.json();
    if (!r.ok || !res.ok) throw new Error(res.error || `failed (${r.status})`);
    status.textContent = res.minted
      ? `Minted new cert "${res.slug}" and built package.`
      : `Built package from existing cert "${res.slug}".`;
    renderCard(callsign, res);
  } catch (e) {
    status.textContent = '';
    alert(e.message);
  } finally {
    btn.disabled = false;
  }
}

function renderCard(callsign, res) {
  document.getElementById('ob-card').hidden = false;
  document.getElementById('ob-card-callsign').textContent = `${callsign} → ${res.server}`;

  const url = new URL(res.url, window.location.href).href;
  qrInto(document.getElementById('ob-qr-tak'), url);
  const urlEl = document.getElementById('ob-tak-url');
  urlEl.innerHTML = '';
  const a = document.createElement('a');
  a.href = res.url;
  a.textContent = url;
  urlEl.appendChild(a);

  if (obConfig && obConfig.mesh_url) {
    document.getElementById('ob-block-mesh').hidden = false;
    qrInto(document.getElementById('ob-qr-mesh'), obConfig.mesh_url);
  }
  if (obConfig && obConfig.wifi_ssid) {
    document.getElementById('ob-block-wifi').hidden = false;
    const psk = obConfig.wifi_psk || '';
    const payload = psk
      ? `WIFI:T:WPA;S:${wifiEscape(obConfig.wifi_ssid)};P:${wifiEscape(psk)};;`
      : `WIFI:T:nopass;S:${wifiEscape(obConfig.wifi_ssid)};;`;
    qrInto(document.getElementById('ob-qr-wifi'), payload);
  }
  document.getElementById('ob-card').scrollIntoView({ behavior: 'smooth' });
}

document.addEventListener('DOMContentLoaded', () => {
  loadConfig();
  document.getElementById('ob-form').addEventListener('submit', generate);
  document.getElementById('ob-print').addEventListener('click', () => window.print());
});
