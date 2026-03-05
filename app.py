import json
import os
import shutil
import requests
from datetime import datetime, timezone
from flask import Flask, jsonify, request, render_template, abort, send_from_directory

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
AREAS_DIR = os.path.join(DATA_DIR, 'areas')
GEO_DIR = os.path.join(DATA_DIR, 'geo')

# ── File registry ─────────────────────────────────────────────────────────────
DATA_FILES = {
    'indicators':        os.path.join(DATA_DIR, 'iw_indicators.json'),
    'airports':          os.path.join(DATA_DIR, 'airports.json'),
    'borders':           os.path.join(DATA_DIR, 'borders.json'),
    'outlook':           os.path.join(DATA_DIR, 'outlook.json'),
    'bm_tracking':       os.path.join(DATA_DIR, 'bm_tracking.json'),
    'activity':          os.path.join(DATA_DIR, 'activity.json'),
    'macro_indicators':  os.path.join(DATA_DIR, 'macro_indicators.json'),
    'comments':          os.path.join(DATA_DIR, 'comments.json'),
    'state_dept':        os.path.join(DATA_DIR, 'state_dept', 'travel_advisories.json'),
}

AREA_SLUGS = ['uae', 'saudi', 'bahrain', 'qatar', 'oman', 'kuwait', 'lebanon']

AREA_FILES = {
    slug: os.path.join(AREAS_DIR, f'{slug}.json')
    for slug in AREA_SLUGS
}

DEFAULT_FILES = {k: v + '.default' for k, v in DATA_FILES.items()}
AREA_DEFAULTS = {k: v + '.default' for k, v in AREA_FILES.items()}

AREA_DISPLAY = {
    'uae':    'United Arab Emirates',
    'saudi':  'Saudi Arabia',
    'bahrain': 'Bahrain',
    'qatar':  'Qatar',
    'oman':   'Oman',
    'kuwait': 'Kuwait',
    'lebanon': 'Lebanon',
}

# Map area slug → country key used in airports.json / borders.json groupings
LIVE_COUNTRY_KEY = {
    'uae': 'UAE',
    'saudi': 'Saudi Arabia',
    'bahrain': 'Bahrain',
    'qatar': 'Qatar',
    'oman': 'Oman',
    'kuwait': 'Kuwait',
    'lebanon': 'Lebanon',
}


# ── Helpers ───────────────────────────────────────────────────────────────────
def load_json(path):
    with open(path, 'r') as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def ensure_defaults():
    for key, src in DATA_FILES.items():
        dst = DEFAULT_FILES[key]
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy(src, dst)
    for slug, src in AREA_FILES.items():
        dst = AREA_DEFAULTS[slug]
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy(src, dst)


ensure_defaults()


def notify_telegram(text: str):
    """Send a Telegram message if env vars are configured. Silent on failure."""
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    if not token or not chat_id:
        return
    try:
        requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'},
            timeout=6,
        )
    except Exception:
        pass  # notification failure must never break the API response


# ── Page routes ───────────────────────────────────────────────────────────────
@app.route('/')
def landing():
    return render_template('index.html', page='landing')


@app.route('/travel')
def travel():
    return render_template('travel.html', page='travel')


@app.route('/uae')
def page_uae():
    return render_template('country.html', page='country', area_slug='uae',
                           area_name=AREA_DISPLAY['uae'])


@app.route('/saudi')
def page_saudi():
    return render_template('country.html', page='country', area_slug='saudi',
                           area_name=AREA_DISPLAY['saudi'])


@app.route('/bahrain')
def page_bahrain():
    return render_template('country.html', page='country', area_slug='bahrain',
                           area_name=AREA_DISPLAY['bahrain'])


@app.route('/qatar')
def page_qatar():
    return render_template('country.html', page='country', area_slug='qatar',
                           area_name=AREA_DISPLAY['qatar'])


@app.route('/oman')
def page_oman():
    return render_template('country.html', page='country', area_slug='oman',
                           area_name=AREA_DISPLAY['oman'])


@app.route('/kuwait')
def page_kuwait():
    return render_template('country.html', page='country', area_slug='kuwait',
                           area_name=AREA_DISPLAY['kuwait'])


@app.route('/lebanon')
def page_lebanon():
    return render_template('country.html', page='country', area_slug='lebanon',
                           area_name=AREA_DISPLAY['lebanon'])


@app.route('/admin')
def page_admin():
    return render_template('admin.html', page='admin')


# ── API: macro data ───────────────────────────────────────────────────────────
@app.route('/api/macro', methods=['GET'])
def api_macro():
    activity = load_json(DATA_FILES['activity'])
    # Macro feed = events tagged macro OR multi-country
    macro_activity = [
        e for e in activity
        if 'macro' in e.get('countries', []) or len(e.get('countries', [])) > 1
    ]
    return jsonify({
        'activity':         activity,          # all events (landing shows all)
        'macro_activity':   macro_activity,
        'macro_indicators': load_json(DATA_FILES['macro_indicators']),
        'bm_tracking':      load_json(DATA_FILES['bm_tracking']),
        'airports':         load_json(DATA_FILES['airports']),
        'fr24_meta':        load_json(os.path.join(DATA_DIR, 'fr24_meta.json')) if os.path.exists(os.path.join(DATA_DIR, 'fr24_meta.json')) else {},
        'state_dept':       load_json(DATA_FILES['state_dept']) if os.path.exists(DATA_FILES['state_dept']) else {},
        'server_time':      datetime.now(timezone.utc).isoformat(),
    })


# ── API: per-area data ────────────────────────────────────────────────────────
@app.route('/api/area/<slug>', methods=['GET'])
def api_area(slug):
    if slug not in AREA_SLUGS:
        abort(404, f'Unknown area: {slug}')
    area = load_json(AREA_FILES[slug])

    # Ensure airports/borders shown on the country page align with the live datasets
    live_key = LIVE_COUNTRY_KEY.get(slug, AREA_DISPLAY.get(slug, slug))
    try:
        airports_all = load_json(DATA_FILES['airports'])
        grp = next((g for g in airports_all if g.get('country') == live_key), None)
        area['airports'] = (grp or {}).get('airports', [])
    except Exception:
        pass

    try:
        borders_all = load_json(DATA_FILES['borders'])
        grp = next((g for g in borders_all if g.get('country') == live_key), None)
        crossings = (grp or {}).get('crossings', [])
        # Convert to the shape expected by the country page renderer
        area['borders'] = [
            {
                'name': c.get('crossing'),
                'status': c.get('flow_status') or c.get('status') or 'UNKNOWN',
                'notes': (c.get('traffic_note') or '').strip() or (c.get('notes') or '').strip(),
            }
            for c in crossings
        ]
    except Exception:
        pass

    activity = load_json(DATA_FILES['activity'])
    area_activity = [
        e for e in activity
        if slug in e.get('countries', []) or 'macro' in e.get('countries', [])
    ]
    state = load_json(DATA_FILES['state_dept']) if os.path.exists(DATA_FILES['state_dept']) else {}
    country_name = AREA_DISPLAY.get(slug)
    state_country = (state.get('countries') or {}).get(country_name) if country_name else None
    if state_country and 'country' not in state_country:
        state_country = dict(state_country, country=country_name)

    return jsonify({
        'area':          area,
        'iw_matrix':     area.get('iw_matrix', []),
        'activity':      area_activity,
        'state_dept':    state_country,
        'server_time':   datetime.now(timezone.utc).isoformat(),
    })


# ── API: comment submission ───────────────────────────────────────────────────
@app.route('/api/comment', methods=['POST'])
def api_comment():
    body = request.get_json(force=True) or {}
    text = (body.get('text') or '').strip()
    if not text:
        abort(400, 'text field required')

    entry = {
        'id':         f"cmt-{int(datetime.now(timezone.utc).timestamp()*1000)}",
        'ts_utc':     datetime.now(timezone.utc).isoformat(),
        'page':       body.get('page', 'landing'),
        'area':       body.get('area', ''),
        'name':       (body.get('name') or '').strip(),
        'contact':    (body.get('contact') or '').strip(),
        'text':       text,
    }

    # Persist
    comments_path = DATA_FILES['comments']
    comments = load_json(comments_path) if os.path.exists(comments_path) else []
    comments.append(entry)
    save_json(comments_path, comments)

    # Notify operator
    page_label = entry['area'] or entry['page']
    who = entry['name'] or 'Anonymous'
    contact_str = f"\nContact: {entry['contact']}" if entry['contact'] else ''
    tg_msg = (
        f"<b>📋 Dashboard change request</b>\n"
        f"Page: <code>{page_label}</code>  |  From: {who}{contact_str}\n\n"
        f"{text}"
    )
    notify_telegram(tg_msg)

    return jsonify({'ok': True, 'id': entry['id']})


# ── Legacy API: full data bundle (backward compat) ────────────────────────────
@app.route('/api/version', methods=['GET'])
def api_version():
    """Return a small version stamp so we can verify what code/data is live behind the tunnel."""
    import subprocess
    try:
        commit = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], cwd=BASE_DIR, text=True).strip()
    except Exception:
        commit = None
    return jsonify({
        'ok': True,
        'commit': commit,
        'server_time_utc': datetime.now(timezone.utc).isoformat(),
        'tunnel_ingress': 'gulf.opnsrcops.com -> 127.0.0.1:5050',
    })


@app.route('/api/data', methods=['GET'])
def get_all_data():
    return jsonify({
        'indicators':  load_json(DATA_FILES['indicators']),
        'airports':    load_json(DATA_FILES['airports']),
        'borders':     load_json(DATA_FILES['borders']),
        'outlook':     load_json(DATA_FILES['outlook']),
        'bm_tracking': load_json(DATA_FILES['bm_tracking']),
        'server_time': datetime.now(timezone.utc).isoformat(),
    })


@app.route('/api/indicators', methods=['GET'])
def get_indicators():
    return jsonify(load_json(DATA_FILES['indicators']))


@app.route('/api/indicators/<int:indicator_id>', methods=['POST'])
def update_indicator(indicator_id):
    body = request.get_json(force=True)
    if not body:
        abort(400, 'JSON body required')
    indicators = load_json(DATA_FILES['indicators'])
    updated = False
    for ind in indicators:
        if ind['id'] == indicator_id:
            for field in ('status', 'time_met', 'notes'):
                if field in body:
                    ind[field] = body[field]
            updated = True
            break
    if not updated:
        abort(404, f'Indicator {indicator_id} not found')
    save_json(DATA_FILES['indicators'], indicators)
    return jsonify({'ok': True, 'indicator': next(i for i in indicators if i['id'] == indicator_id)})


@app.route('/api/macro_indicators/<int:indicator_id>', methods=['POST'])
def update_macro_indicator(indicator_id):
    body = request.get_json(force=True)
    if not body:
        abort(400, 'JSON body required')
    indicators = load_json(DATA_FILES['macro_indicators'])
    updated = False
    for ind in indicators:
        if ind['id'] == indicator_id:
            for field in ('status', 'notes', 'description'):
                if field in body:
                    ind[field] = body[field]
            ind['last_updated'] = datetime.now(timezone.utc).isoformat()
            updated = True
            break
    if not updated:
        abort(404, f'Macro indicator {indicator_id} not found')
    save_json(DATA_FILES['macro_indicators'], indicators)
    return jsonify({'ok': True})


@app.route('/api/area/<slug>', methods=['POST'])
def update_area(slug):
    if slug not in AREA_SLUGS:
        abort(404)
    body = request.get_json(force=True)
    if not body:
        abort(400, 'JSON body required')
    save_json(AREA_FILES[slug], body)
    return jsonify({'ok': True, 'saved_at': datetime.now(timezone.utc).isoformat()})


@app.route('/api/bm_tracking', methods=['GET'])
def get_bm_tracking():
    return jsonify(load_json(DATA_FILES['bm_tracking']))


@app.route('/api/bm_tracking/day', methods=['POST'])
def update_bm_day():
    body = request.get_json(force=True)
    if not body:
        abort(400, 'JSON body required')
    tracking = load_json(DATA_FILES['bm_tracking'])
    day_num = body.get('day')
    if not day_num:
        abort(400, 'day field required')
    found = False
    for entry in tracking['daily_log']:
        if entry['day'] == day_num:
            entry.update({k: v for k, v in body.items() if k != 'day'})
            found = True
            break
    if not found:
        tracking['daily_log'].append(body)
        tracking['daily_log'].sort(key=lambda x: x['day'])
    log = tracking['daily_log']
    n = len(log)
    if n > 0:
        tracking['totals']['days_tracked'] = n
        tracking['totals']['ballistic_missiles'] = sum(e.get('bm_announced', 0) for e in log)
        tracking['totals']['drones'] = sum(e.get('drones_announced', 0) for e in log)
        tracking['totals']['cruise_missiles'] = sum(e.get('cm_announced', 0) for e in log)
        tracking['totals']['total_projectiles'] = (
            tracking['totals']['ballistic_missiles'] +
            tracking['totals']['drones'] +
            tracking['totals']['cruise_missiles']
        )
        tracking['averages']['bm_per_day'] = round(tracking['totals']['ballistic_missiles'] / n, 1)
        tracking['averages']['drones_per_day'] = round(tracking['totals']['drones'] / n, 1)
        tracking['averages']['total_per_day'] = round(tracking['totals']['total_projectiles'] / n, 1)
    tracking['depletion']['last_updated'] = datetime.now(timezone.utc).isoformat()
    save_json(DATA_FILES['bm_tracking'], tracking)
    return jsonify({'ok': True, 'tracking': tracking})


@app.route('/api/update', methods=['POST'])
def update_data():
    body = request.get_json(force=True)
    if not body:
        abort(400, 'JSON body required')
    section = body.get('section')
    if section not in DATA_FILES:
        abort(400, f'Unknown section: {section}. Valid: {list(DATA_FILES.keys())}')
    payload = body.get('data')
    if payload is None:
        abort(400, 'data field required')
    save_json(DATA_FILES[section], payload)
    return jsonify({'ok': True, 'section': section, 'saved_at': datetime.now(timezone.utc).isoformat()})


GEO_DIR = os.path.join(DATA_DIR, 'geo')

@app.route('/api/geo/<path:filename>')
def serve_geo(filename):
    """Serve GeoJSON/CSV/JSON files for ArcGIS import.

    Supports a small allowlist of top-level files plus daily strike layers under
    `strikemap_daily_r001/`.
    """
    # Normalize + block traversal
    filename = filename.lstrip('/').replace('..', '')

    allowed_top = {
        'airports.geojson',
        'border_crossings.geojson',
        'strike_locations.geojson',
        'gulf_aor_all_layers.csv',
        'renderer_status.json',
        'renderer_strikes.json',
        'renderer_airports.json',
        'renderer_idf_orange.json',
        'ground_routes.geojson',
        # StrikeMap-derived layers (combined)
        'strikemap_incidents_filtered_deduped.geojson',
        'strikemap_incidents_filtered_deduped_r001.geojson',
        'strikemap_master_strikes_against_iran_r001.geojson',
        'strikemap_master_iran_outbound_kinetic_r001.geojson',
        # ArcGIS Experience-derived layers (deduped against local strike DB)
        'idf_lebanon_2026_03_04_deduped.geojson',
        'iranian_attacks_2026_deduped.geojson',
        'us_bases_used_middle_east.geojson',
    }

    allowed = False
    if filename in allowed_top:
        allowed = True
    # Allow daily files under a fixed directory
    if filename.startswith('strikemap_daily_r001/') and filename.endswith('.geojson'):
        allowed = True

    if not allowed:
        abort(404)

    path = os.path.join(GEO_DIR, filename)
    if not os.path.exists(path):
        abort(404)

    if filename.endswith('.geojson'):
        mime = 'application/geo+json'
    elif filename.endswith('.csv'):
        mime = 'text/csv'
    else:
        mime = 'application/json'

    from flask import send_file
    return send_file(path, mimetype=mime, as_attachment=False)

@app.route('/geo')
def geo_index():
    """Download page for GeoJSON/CSV files."""
    BASE_URL = request.host_url.rstrip('/')
    layers = [
        ('airports.geojson',         'Airports',         'renderer_status.json',  'status field → OPEN/RESTRICTED/CLOSED'),
        ('border_crossings.geojson', 'Border Crossings', 'renderer_status.json',  'status field → OPEN/RESTRICTED/CLOSED — refreshed every 30min via Google Directions API'),
        ('strike_locations.geojson', 'Strike Locations', 'renderer_strikes.json', 'severity field → CRITICAL/HIGH/MEDIUM/LOW'),
        ('strikemap_incidents_filtered_deduped_r001.geojson', 'Kinetic Events (StrikeMap-derived, filtered/deduped)', 'renderer_strikes.json', 'Daily files available under /api/geo/strikemap_daily_r001/ (toggle by day in ArcGIS).'),
        ('idf_lebanon_2026_03_04_deduped.geojson', 'IDF Strikes in Lebanon (Automated) — 4 Mar (deduped vs local DB)', 'renderer_idf_orange.json', 'Source: ArcGIS Experience layer Lebanon_Israeli_Strikes_04MARCH_XYTableToPoint/FeatureServer/0'),
        ('iranian_attacks_2026_deduped.geojson', 'Iranian Attacks in 2026 (deduped vs local DB)', 'renderer_strikes.json', 'Source: ArcGIS Experience layer IranianAttack2026/FeatureServer/0'),
        ('us_bases_used_middle_east.geojson', 'Bases used by the US in the Middle East', 'renderer_strikes.json', 'Source: ArcGIS Experience layer US_bases_in_the_Middle_East/FeatureServer/0'),
    ]

    def layer_block(fname, title, renderer, note):
        url = f'{BASE_URL}/api/geo/{fname}'
        rurl = f'{BASE_URL}/api/geo/{renderer}'
        return f'''
        <div style="border:1px solid #30363d;border-radius:6px;padding:16px;margin-bottom:14px">
          <div style="color:#f0a500;font-weight:700;font-size:.95rem;margin-bottom:6px">{title}</div>
          <div style="margin-bottom:8px">
            <span style="color:#8b949e;font-size:.8rem">GeoJSON URL:</span><br>
            <code style="color:#58a6ff;font-size:.8rem;word-break:break-all">{url}</code>
          </div>
          <div style="margin-bottom:8px">
            <span style="color:#8b949e;font-size:.8rem">Renderer JSON:</span><br>
            <code style="color:#58a6ff;font-size:.8rem;word-break:break-all">{rurl}</code>
          </div>
          <div style="color:#8b949e;font-size:.75rem">{note}</div>
        </div>'''

    blocks = ''.join(layer_block(*l) for l in layers)
    csv_url = f'{BASE_URL}/api/geo/gulf_aor_all_layers.csv'

    # Daily strike layers (StrikeMap-derived)
    daily_dir = os.path.join(GEO_DIR, 'strikemap_daily_r001')
    daily_links = ''
    if os.path.isdir(daily_dir):
        files = sorted([f for f in os.listdir(daily_dir) if f.endswith('.geojson')], reverse=True)
        # show most recent 10 for copy/paste
        items = []
        for f in files[:10]:
            url = f"{BASE_URL}/api/geo/strikemap_daily_r001/{f}"
            items.append(f"<div><code style=\"color:#58a6ff;font-size:.8rem\">{url}</code></div>")
        daily_links = ''.join(items)

    html = f'''<!doctype html><html><head><title>Gulf AOR — GeoData</title>
    <style>
      body{{background:#0d1117;color:#c9d1d9;font-family:monospace;padding:40px;max-width:860px;margin:0 auto}}
      h1{{color:#f0a500;margin-bottom:4px}} h2{{color:#c9d1d9;font-size:.9rem;margin:24px 0 10px}}
      code{{background:#161b22;padding:2px 6px;border-radius:3px}}
      .step{{background:#161b22;border-left:3px solid #f0a500;padding:10px 14px;margin:6px 0;font-size:.82rem}}
      a{{color:#58a6ff}}
    </style></head>
    <body>
    <h1>Gulf AOR — Live GeoJSON Layers</h1>
    <p style="color:#8b949e;font-size:.82rem">Border crossings refresh every 30 min via Google Directions API. Airports update on manual data push.</p>

    <h2>LAYERS</h2>
    {blocks}

    <h2>DAILY KINETIC LAYERS (STRIKEMAP-DERIVED)</h2>
    <div class="step">Load these as separate ArcGIS layers to reduce clutter. Most recent 10 shown:</div>
    {daily_links if daily_links else '<div class="step">(No daily files found on server)</div>'}

    <div style="margin-bottom:14px">
      <div style="color:#f0a500;font-weight:700;font-size:.95rem;margin-bottom:6px">All Layers Combined (CSV)</div>
      <code style="color:#58a6ff;font-size:.8rem">{csv_url}</code>
    </div>

    <h2>HOW TO LOAD IN ARCGIS ONLINE — UNIQUE VALUE SYMBOLOGY</h2>
    <div class="step">1. Open your map → <b>Add</b> → <b>Add layer from URL</b></div>
    <div class="step">2. Paste the GeoJSON URL → click <b>Add to map</b></div>
    <div class="step">3. In the layer panel → click <b>Styles</b> → choose <b>Types (unique symbols)</b></div>
    <div class="step">4. Set field to <b>status</b> (airports/borders) or <b>severity</b> (strikes)</div>
    <div class="step">5. For each value: OPEN → green circle, RESTRICTED → amber circle, CLOSED → red ✕</div>
    <div class="step">6. Enable <b>Refresh interval</b> on border crossings layer → set to 30 min to track live updates</div>

    <h2>SYMBOL KEY</h2>
    <div class="step">🟢 OPEN &nbsp; 🟡 RESTRICTED / Congested &nbsp; 🔴 CLOSED<br>
    Strikes: ◆ CRITICAL (red) ◆ HIGH (amber) ◆ MODERATE (yellow) ◆ LOW (green)</div>

    <p style="color:#444;font-size:.75rem;margin-top:32px">gulf.opnsrcops.com | auto-updated</p>
    </body></html>'''
    return html

# ── Admin API ─────────────────────────────────────────────────────────────────

@app.route('/api/admin/airport/<iata>', methods=['POST'])
def admin_airport(iata):
    iata = iata.upper()
    body = request.get_json() or {}
    STATUS_MAP = {
        'OPEN':       {'code':1,'color':'#2ea043','icon':'circle-green','label':'Open','marker-color':'#2ea043','marker-size':'medium','marker-symbol':'airport'},
        'OBSTRUCTED': {'code':2,'color':'#f0a500','icon':'circle-amber','label':'Obstructed','marker-color':'#f0a500','marker-size':'medium','marker-symbol':'airport'},
        'CLOSED':     {'code':3,'color':'#f85149','icon':'circle-red',  'label':'Closed','marker-color':'#f85149','marker-size':'medium','marker-symbol':'airport'},
    }
    status = body.get('status','').upper()
    if status not in STATUS_MAP:
        return jsonify({'ok':False,'error':f'Invalid status: {status}'})
    meta = STATUS_MAP[status]
    NOW  = datetime.now(timezone.utc).isoformat()

    # Update airports.json
    airports = load_json(DATA_FILES['airports'])
    found = False
    for group in airports:
        for ap in group['airports']:
            if ap['iata'] == iata:
                ap['status']           = status
                ap['status_code']      = meta['code']
                ap['marker_color']     = meta['color']
                ap['icon_type']        = meta['icon']
                ap['status_label']     = meta['label']
                ap['last_updated']     = NOW
                if body.get('notes')            is not None: ap['notes']            = body['notes']
                if body.get('airspace')         is not None: ap['airspace']         = body['airspace']
                if body.get('intl_canceled')    is not None: ap['intl_canceled']    = body['intl_canceled']
                if body.get('domestic_canceled') is not None: ap['domestic_canceled']= body['domestic_canceled']
                found = True
    if not found:
        return jsonify({'ok':False,'error':f'{iata} not found'})
    save_json(DATA_FILES['airports'], airports)

    # Update airports.geojson
    geo_path = os.path.join(BASE_DIR, 'data', 'geo', 'airports.geojson')
    geo = load_json(geo_path)
    for feat in geo['features']:
        p = feat['properties']
        if p['iata'] == iata:
            p['status']          = status
            p['status_code']     = meta['code']
            p['marker_color']    = meta['color']
            p['icon_type']       = meta['icon']
            p['status_label']    = meta['label']
            p['marker-color']    = meta['marker-color']
            p['marker-size']     = meta['marker-size']
            p['marker-symbol']   = meta['marker-symbol']
            p['last_updated']    = NOW
            if body.get('notes')            is not None: p['notes']            = body['notes']
            if body.get('airspace')         is not None: p['airspace']         = body['airspace']
            if body.get('intl_canceled')    is not None: p['intl_canceled']    = body['intl_canceled']
            if body.get('domestic_canceled') is not None: p['domestic_canceled']= body['domestic_canceled']
    save_json(geo_path, geo)
    return jsonify({'ok':True,'iata':iata,'status':status})


@app.route('/api/admin/border', methods=['POST'])
def admin_border():
    body     = request.get_json() or {}
    crossing = body.get('crossing', body.get('name','')).strip()
    status   = body.get('status','').upper()
    notes    = body.get('notes')
    if status not in ('OPEN','RESTRICTED','CLOSED'):
        return jsonify({'ok':False,'error':f'Invalid status: {status}'})
    NOW = datetime.now(timezone.utc).isoformat()

    # borders.json
    BORDERS_FILE = os.path.join(DATA_DIR, 'borders.json')
    borders = load_json(BORDERS_FILE)
    found = False
    for group in borders:
        for cr in group.get('crossings', []):
            cr_id = cr.get('crossing', cr.get('name',''))
            if cr_id == crossing:
                cr['status'] = status
                cr['last_updated'] = NOW
                if notes is not None: cr['notes'] = notes
                found = True
    if not found:
        return jsonify({'ok':False,'error':f'Crossing "{crossing}" not found'})
    save_json(BORDERS_FILE, borders)

    # border_crossings.geojson
    geo_path = os.path.join(BASE_DIR, 'data', 'geo', 'border_crossings.geojson')
    if os.path.exists(geo_path):
        COLOR_MAP = {'OPEN':'#2ea043','RESTRICTED':'#f0a500','CLOSED':'#f85149'}
        geo = load_json(geo_path)
        for feat in geo['features']:
            p = feat['properties']
            cr_id = p.get('crossing', p.get('name',''))
            if cr_id == crossing:
                p['status']       = status
                p['marker_color'] = COLOR_MAP.get(status,'#8b949e')
                p['marker-color'] = COLOR_MAP.get(status,'#8b949e')
                p['last_updated'] = NOW
                if notes is not None: p['notes'] = notes
        save_json(geo_path, geo)
    return jsonify({'ok':True,'name':name,'status':status})


@app.route('/api/admin/event', methods=['POST'])
def admin_event():
    body = request.get_json() or {}
    title = body.get('title','').strip()
    if not title:
        return jsonify({'ok':False,'error':'title required'})

    activity = load_json(DATA_FILES['activity'])
    # Auto-generate next ID
    existing_ids = [e.get('id','') for e in activity]
    nums = []
    for eid in existing_ids:
        parts = eid.rsplit('-', 1)
        if len(parts) == 2 and parts[1].isdigit():
            nums.append(int(parts[1]))
    next_num = max(nums, default=0) + 1
    new_id   = f'evt-admin-{next_num:03d}'

    event = {
        'id':            new_id,
        'timestamp_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'category':      body.get('category', 'other'),
        'title':         title,
        'summary':       body.get('summary', ''),
        'country':       body.get('country', ''),
        'severity':      body.get('severity', 'MEDIUM'),
        'source':        body.get('source', ''),
    }
    activity.append(event)
    save_json(DATA_FILES['activity'], activity)
    return jsonify({'ok':True,'id':new_id})


@app.route('/api/admin/iw/<ind_id>', methods=['POST'])
def admin_iw(ind_id):
    body   = request.get_json() or {}
    status = body.get('status','').upper()
    notes  = body.get('notes')
    if status not in ('MET','WATCH','UNMET'):
        return jsonify({'ok':False,'error':f'Invalid status: {status}'})
    indicators = load_json(DATA_FILES['macro_indicators'])
    found = False
    for ind in indicators:
        if ind.get('id') == ind_id or ind.get('slug') == ind_id:
            ind['status'] = status
            if notes is not None: ind['notes'] = notes
            found = True
    if not found:
        return jsonify({'ok':False,'error':f'Indicator {ind_id} not found'})
    save_json(DATA_FILES['macro_indicators'], indicators)
    return jsonify({'ok':True,'id':ind_id,'status':status})


@app.route('/api/reset', methods=['POST'])
def reset_defaults():
    # Reset flat data files
    for key, src in DEFAULT_FILES.items():
        if os.path.exists(src):
            shutil.copy(src, DATA_FILES[key])
    # Reset area files
    for slug, src in AREA_DEFAULTS.items():
        if os.path.exists(src):
            shutil.copy(src, AREA_FILES[slug])
    return jsonify({'ok': True, 'message': 'All data reset to defaults'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, debug=True)
