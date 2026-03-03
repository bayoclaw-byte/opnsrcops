import json
import os
from datetime import datetime, timezone
from flask import Flask, jsonify, request, render_template, abort

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')

DATA_FILES = {
    'indicators':   os.path.join(DATA_DIR, 'iw_indicators.json'),
    'airports':     os.path.join(DATA_DIR, 'airports.json'),
    'borders':      os.path.join(DATA_DIR, 'borders.json'),
    'outlook':      os.path.join(DATA_DIR, 'outlook.json'),
    'bm_tracking':  os.path.join(DATA_DIR, 'bm_tracking.json'),
}

DEFAULT_FILES = {k: v + '.default' for k, v in DATA_FILES.items()}


def load_json(path):
    with open(path, 'r') as f:
        return json.load(f)


def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def ensure_defaults():
    for key, src in DATA_FILES.items():
        dst = DEFAULT_FILES[key]
        if os.path.exists(src) and not os.path.exists(dst):
            import shutil
            shutil.copy(src, dst)


ensure_defaults()


@app.route('/')
def index():
    return render_template('index.html')


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


@app.route('/api/bm_tracking', methods=['GET'])
def get_bm_tracking():
    return jsonify(load_json(DATA_FILES['bm_tracking']))


@app.route('/api/bm_tracking/day', methods=['POST'])
def update_bm_day():
    """Add or update a single day entry in the BM daily log."""
    body = request.get_json(force=True)
    if not body:
        abort(400, 'JSON body required')
    tracking = load_json(DATA_FILES['bm_tracking'])
    day_num = body.get('day')
    if not day_num:
        abort(400, 'day field required')
    # Find or create
    found = False
    for entry in tracking['daily_log']:
        if entry['day'] == day_num:
            entry.update({k: v for k, v in body.items() if k != 'day'})
            found = True
            break
    if not found:
        tracking['daily_log'].append(body)
        tracking['daily_log'].sort(key=lambda x: x['day'])
    # Recalculate totals and averages
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


@app.route('/api/reset', methods=['POST'])
def reset_defaults():
    import shutil
    for key, src in DEFAULT_FILES.items():
        if os.path.exists(src):
            shutil.copy(src, DATA_FILES[key])
    return jsonify({'ok': True, 'message': 'All data reset to defaults'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, debug=True)
