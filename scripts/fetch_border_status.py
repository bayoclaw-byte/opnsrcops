#!/usr/bin/env python3
"""
fetch_border_status.py
Queries Google Directions API (with traffic) for each border crossing,
derives OPEN/RESTRICTED/CLOSED status from travel-time ratio,
and updates data/borders.json + data/geo/border_crossings.geojson + CSV.

Usage:
    GOOGLE_MAPS_API_KEY=<key> python3 scripts/fetch_border_status.py
"""

import json, os, csv, math, time, requests
from datetime import datetime, timezone

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BORDERS_F  = os.path.join(BASE_DIR, 'data', 'borders.json')
GEO_F      = os.path.join(BASE_DIR, 'data', 'geo', 'border_crossings.geojson')
AIRPORTS_F = os.path.join(BASE_DIR, 'data', 'geo', 'airports.geojson')
STRIKES_F  = os.path.join(BASE_DIR, 'data', 'geo', 'strike_locations.geojson')
CSV_F      = os.path.join(BASE_DIR, 'data', 'geo', 'gulf_aor_all_layers.csv')

API_KEY    = os.environ.get('GOOGLE_MAPS_API_KEY', '').strip()
DIRECTIONS = 'https://maps.googleapis.com/maps/api/directions/json'

# Offset distance in degrees (~5 km)
OFFSET = 0.045

# For each border pair: (bearing_from_A_to_B_degrees, side_A_label, side_B_label)
# Origin placed on side A, destination on side B
PAIR_BEARING = {
    'UAE/Oman':    (90,  'UAE',    'Oman'),
    'Oman/UAE':    (270, 'Oman',   'UAE'),
    'UAE/Saudi':   (225, 'UAE',    'Saudi'),
    'Saudi/Oman':  (90,  'Saudi',  'Oman'),
    'Saudi/Kuwait':(0,   'Saudi',  'Kuwait'),
    'Kuwait/Saudi':(180, 'Kuwait', 'Saudi'),
    'Saudi/Jordan':(315, 'Saudi',  'Jordan'),
    'Saudi/Yemen': (180, 'Saudi',  'Yemen'),
    'Saudi/Iraq':  (0,   'Saudi',  'Iraq'),
    'Bahrain/Saudi':(270,'Bahrain','Saudi'),
    'Saudi/Qatar':   (90,  'Saudi',  'Qatar'),
    'Qatar/Saudi':   (270, 'Qatar',  'Saudi'),
}


def offset_point(lat, lon, bearing_deg, dist_deg=OFFSET):
    """Move a point dist_deg in bearing_deg direction."""
    b = math.radians(bearing_deg)
    dlat = dist_deg * math.cos(b)
    dlon = dist_deg * math.sin(b) / max(math.cos(math.radians(lat)), 0.001)
    return round(lat + dlat, 6), round(lon + dlon, 6)


def query_directions(origin, destination):
    """
    Returns (duration_secs, duration_in_traffic_secs, status_str).
    status_str: 'OK', 'ZERO_RESULTS', 'ERROR'
    """
    params = {
        'origin':       f'{origin[0]},{origin[1]}',
        'destination':  f'{destination[0]},{destination[1]}',
        'departure_time': int(time.time()),
        'traffic_model': 'best_guess',
        'key': API_KEY,
    }
    try:
        r = requests.get(DIRECTIONS, params=params, timeout=10)
        data = r.json()
        api_status = data.get('status', 'ERROR')
        if api_status == 'OK':
            leg = data['routes'][0]['legs'][0]
            dur = leg['duration']['value']
            dur_traffic = leg.get('duration_in_traffic', leg['duration'])['value']
            return dur, dur_traffic, 'OK'
        return None, None, api_status
    except Exception as e:
        return None, None, f'ERROR: {e}'


def derive_status(dur, dur_traffic, api_status):
    """Derive OPEN/RESTRICTED/CLOSED from API result."""
    if api_status == 'ZERO_RESULTS':
        return 'CLOSED', 'No route returned by Directions API'
    if api_status != 'OK' or dur is None:
        return 'UNKNOWN', f'API status: {api_status}'
    ratio = dur_traffic / dur if dur > 0 else 1.0
    wait_min = max(0, round((dur_traffic - dur) / 60))
    if ratio >= 3.0:
        return 'RESTRICTED', f'Traffic delay {wait_min}min ({ratio:.1f}x normal)'
    return 'OPEN', f'~{wait_min}min delay ({ratio:.1f}x normal)' if wait_min > 2 else 'Normal flow'


def main():
    if not API_KEY:
        print('ERROR: GOOGLE_MAPS_API_KEY not set')
        return

    NOW = datetime.now(timezone.utc).isoformat()
    geo  = json.load(open(GEO_F))
    borders = json.load(open(BORDERS_F))

    # Build name→feature map
    feat_map = {f['properties']['name']: f for f in geo['features']}

    results = {}
    for feat in geo['features']:
        p    = feat['properties']
        name = p['name']
        pair = p.get('border_pair', '')
        lon, lat = feat['geometry']['coordinates']

        bearing_info = PAIR_BEARING.get(pair)
        if not bearing_info:
            print(f'  SKIP {name} — no bearing config for pair "{pair}"')
            continue

        bearing, side_a, side_b = bearing_info
        origin = offset_point(lat, lon, (bearing + 180) % 360)  # behind crossing
        dest   = offset_point(lat, lon, bearing)                 # past crossing

        print(f'  Querying {name} ({pair})...', end=' ', flush=True)
        dur, dur_t, api_status = query_directions(origin, dest)
        status, traffic_note   = derive_status(dur, dur_t, api_status)
        print(f'{status} — {traffic_note}')

        results[name] = {
            'status': status,
            'traffic_note': traffic_note,
            'duration_secs': dur,
            'duration_traffic_secs': dur_t,
            'last_live_check': NOW,
        }

        # Update GeoJSON feature
        p['status']       = status
        p['status_code']  = {'OPEN':1,'RESTRICTED':2,'CLOSED':3,'UNKNOWN':0}.get(status,0)
        p['traffic_note'] = traffic_note
        p['last_updated'] = NOW
        time.sleep(0.12)  # ~8 req/sec — well under limit

    # Update borders.json
    for group in borders:
        for c in group['crossings']:
            r = results.get(c['crossing'])
            if r:
                c['status']       = r['status']
                c['traffic_note'] = r['traffic_note']
                c['last_updated'] = r['last_live_check']

    with open(GEO_F, 'w') as f:
        json.dump(geo, f, indent=2)
    with open(BORDERS_F, 'w') as f:
        json.dump(borders, f, indent=2)

    # Rebuild combined CSV
    airports_geo = json.load(open(AIRPORTS_F))
    strikes_geo  = json.load(open(STRIKES_F))
    rows = []
    for feat in airports_geo['features']:
        p2 = feat['properties']
        rows.append({'layer':'airport','name':p2['iata'],'full_name':p2.get('name',p2['iata']),
            'longitude':feat['geometry']['coordinates'][0],'latitude':feat['geometry']['coordinates'][1],
            'status':p2['status'],'notes':p2.get('notes','')[:120],'country':p2['country'],'last_updated':p2['last_updated']})
    for feat in geo['features']:
        p2 = feat['properties']
        rows.append({'layer':'border_crossing','name':p2['name'],'full_name':p2['border_pair'],
            'longitude':feat['geometry']['coordinates'][0],'latitude':feat['geometry']['coordinates'][1],
            'status':p2['status'],'notes':p2.get('notes','')[:120],'country':p2['country_group'],'last_updated':p2['last_updated']})
    for feat in strikes_geo['features']:
        p2 = feat['properties']
        rows.append({'layer':'strike','name':p2['id'],'full_name':p2['title'],
            'longitude':feat['geometry']['coordinates'][0],'latitude':feat['geometry']['coordinates'][1],
            'status':p2['severity'].upper(),'notes':p2.get('summary','')[:120],'country':p2['countries'],'last_updated':p2['timestamp_utc']})
    with open(CSV_F, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['layer','name','full_name','longitude','latitude','status','notes','country','last_updated'])
        w.writeheader()
        w.writerows(rows)

    print(f'\nDone. {len(results)} crossings checked. Updated borders.json, GeoJSON, CSV.')


if __name__ == '__main__':
    main()
