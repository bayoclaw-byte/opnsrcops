#!/usr/bin/env python3
"""
fetch_fr24.py — single Gulf-wide bounds query, attribute flights to nearest airport.
Respects FR24 rate limits (one request per run).
"""

import json, os, math, requests, time
from datetime import datetime, timezone

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AIRPORTS_F = os.path.join(BASE_DIR, 'data', 'airports.json')
GEO_F      = os.path.join(BASE_DIR, 'data', 'geo', 'airports.geojson')
FR24_KEY   = os.environ.get('FR24_API_KEY', '').strip()

HEADERS = {
    'Accept':         'application/json',
    'Accept-Version': 'v1',
    'Authorization':  f'Bearer {FR24_KEY}',
}

AIRPORT_COORDS = {
    'DXB': (25.2532, 55.3657), 'AUH': (24.4330, 54.6511),
    'DWC': (24.8963, 55.1607), 'SHJ': (25.3285, 55.5173),
    'BAH': (26.2708, 50.6336), 'MCT': (23.5932, 58.2844),
    'RUH': (24.9576, 46.6988), 'DMM': (26.4712, 49.7979),
    'JED': (21.6796, 39.1565), 'HOF': (25.2853, 49.4852),
    'DOH': (25.2731, 51.6080),
    'KWI': (29.2267, 47.9689),
}
CAPTURE_RADIUS_DEG = 0.5   # ~55km — attribute flight to airport if within this


def haversine_deg(lat1, lon1, lat2, lon2):
    return math.sqrt((lat1-lat2)**2 + (lon1-lon2)**2)


def nearest_airport(lat, lon):
    best, dist = None, 9999
    for iata, (alat, alon) in AIRPORT_COORDS.items():
        d = haversine_deg(lat, lon, alat, alon)
        if d < dist:
            best, dist = iata, d
    return (best, dist) if dist <= CAPTURE_RADIUS_DEG else (None, dist)


def main():
    if not FR24_KEY:
        print('ERROR: FR24_API_KEY not set')
        return

    NOW = datetime.now(timezone.utc).isoformat()

    # Single broad Gulf query — N=35, S=15, W=35, E=65
    # NOTE: API plan caps response at 20 items; rate limit 10 req/min; 60k credits/month
    print(f'FR24 Gulf scan — {NOW}')
    try:
        r = requests.get(
            'https://fr24api.flightradar24.com/api/live/flight-positions/light',
            headers=HEADERS,
            params={'bounds': '35,15,35,65', 'limit': 20},
            timeout=15,
        )
        if r.status_code != 200:
            print(f'API error {r.status_code}: {r.text[:200]}')
            return
        flights = r.json().get('data', [])
    except Exception as e:
        print(f'Request failed: {e}')
        return

    total = len(flights)
    capped = total >= 20
    print(f'Total flights in Gulf AOR: {total}{"  ⚠ AT RESPONSE CAP (20)" if capped else ""}')

    # Attribute to nearest airport
    by_airport = {iata: [] for iata in AIRPORT_COORDS}
    unattributed = []
    for f in flights:
        lat, lon = f.get('lat', 0), f.get('lon', 0)
        iata, dist = nearest_airport(lat, lon)
        if iata:
            by_airport[iata].append(f.get('callsign', '?'))
        else:
            unattributed.append(f.get('callsign', '?'))

    for iata, calls in by_airport.items():
        print(f'  {iata}: {len(calls)} flights  [{", ".join(calls[:4])}]')

    if unattributed:
        print(f'  (unattributed: {len(unattributed)})')

    # Update airports.json
    airports = json.load(open(AIRPORTS_F))
    for group in airports:
        for ap in group['airports']:
            iata = ap['iata']
            calls = by_airport.get(iata, [])
            ap['live_flights']     = len(calls)
            ap['live_callsigns']   = calls[:6]
            ap['live_checked_utc'] = NOW

    with open(AIRPORTS_F, 'w') as f:
        json.dump(airports, f, indent=2)

    # Update GeoJSON
    geo = json.load(open(GEO_F))
    for feat in geo['features']:
        iata = feat['properties']['iata']
        calls = by_airport.get(iata, [])
        feat['properties']['live_flights']     = len(calls)
        feat['properties']['live_callsigns']   = ', '.join(calls[:5])
        feat['properties']['live_checked_utc'] = NOW

    with open(GEO_F, 'w') as f:
        json.dump(geo, f, indent=2)

    print(f'Done. {sum(len(v) for v in by_airport.values())} attributed, {len(unattributed)} unattributed.')

    # Store scan meta for dashboard
    meta_path = os.path.join(BASE_DIR, 'data', 'fr24_meta.json')
    with open(meta_path, 'w') as f:
        json.dump({
            'last_scan_utc':   NOW,
            'total_gulf_flights': total,
            'capped':          capped,
            'plan_limit':      20,
            'rate_limit_rpm':  10,
            'credits_monthly': 60000,
        }, f, indent=2)

    # Persist per-airport counts to support 0→>0 reopening detection across runs
    counts_path = os.path.join(BASE_DIR, 'data', 'fr24_airport_counts.json')
    prev_counts = {}
    try:
        if os.path.exists(counts_path):
            prev = json.load(open(counts_path))
            prev_counts = prev.get('counts', {}) or {}
    except Exception:
        prev_counts = {}

    curr_counts = {iata: len(calls) for iata, calls in by_airport.items()}
    reopen = [
        iata for iata, c in curr_counts.items()
        if c > 0 and int(prev_counts.get(iata, 0) or 0) == 0
    ]

    with open(counts_path, 'w') as f:
        json.dump({
            'last_scan_utc': NOW,
            'counts': curr_counts,
            'unattributed': len(unattributed),
            'total_gulf_flights': total,
            'reopen_iata': reopen,
        }, f, indent=2)

    if reopen:
        # Machine-parseable marker line for cron/agent
        print('REOPEN_INDICATOR: ' + ','.join(reopen))


if __name__ == '__main__':
    main()
