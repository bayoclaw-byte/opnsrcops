import os, json, math
from datetime import datetime, timezone
import requests

# Generates GeoJSON LineStrings from Google Directions API using overview_polyline.
# API key must be provided via env var GOOGLE_MAPS_API_KEY.
# NOTE: Do not commit API keys.

ROUTES = [
    {
        "route_id": "bahrain_to_riyadh",
        "name": "Bahrain → Riyadh",
        "origin": {"name": "Bahrain", "lat": 26.178073, "lon": 50.501016},
        "destination": {"name": "Riyadh", "lat": 24.861517, "lon": 46.890909},
        "line_color": "#f97316",
        "risk_note": "Overland corridor; verify border posture and fuel availability.",
    },
    {
        "route_id": "bahrain_to_muscat",
        "name": "Bahrain → Muscat",
        "origin": {"name": "Bahrain", "lat": 26.178073, "lon": 50.501016},
        "destination": {"name": "Muscat", "lat": 23.567300, "lon": 58.176156},
        "line_color": "#f97316",
        "risk_note": "Overland corridor; verify KSA-UAE/Oman border processing delays.",
    },
    {
        "route_id": "doha_to_riyadh",
        "name": "Doha → Riyadh",
        "origin": {"name": "Doha", "lat": 25.153197, "lon": 51.268320},
        "destination": {"name": "Riyadh", "lat": 24.861517, "lon": 46.890909},
        "line_color": "#22c55e",
        "risk_note": "Primary overland corridor; confirm KSA-QAT border posture.",
    },
    {
        "route_id": "doha_to_muscat",
        "name": "Doha → Muscat",
        "origin": {"name": "Doha", "lat": 25.153197, "lon": 51.268320},
        "destination": {"name": "Muscat", "lat": 23.567300, "lon": 58.176156},
        "line_color": "#22c55e",
        "risk_note": "Long corridor; plan redundancy and overnight stops.",
    },
    {
        "route_id": "dubai_to_riyadh",
        "name": "Dubai → Riyadh",
        "origin": {"name": "Dubai", "lat": 25.217842, "lon": 55.577685},
        "destination": {"name": "Riyadh", "lat": 24.861517, "lon": 46.890909},
        "line_color": "#3b82f6",
        "risk_note": "Primary overland corridor; monitor KSA-UAE border throughput.",
    },
    {
        "route_id": "dubai_to_muscat",
        "name": "Dubai → Muscat",
        "origin": {"name": "Dubai", "lat": 25.217842, "lon": 55.577685},
        "destination": {"name": "Muscat", "lat": 23.567300, "lon": 58.176156},
        "line_color": "#3b82f6",
        "risk_note": "Primary UAE→Oman corridor; expect increased processing time.",
    },
]


def decode_polyline(polyline: str):
    # Google polyline algorithm
    coords = []
    index = 0
    lat = 0
    lng = 0
    length = len(polyline)

    while index < length:
        shift = 0
        result = 0
        while True:
            b = ord(polyline[index]) - 63
            index += 1
            result |= (b & 0x1f) << shift
            shift += 5
            if b < 0x20:
                break
        dlat = ~(result >> 1) if (result & 1) else (result >> 1)
        lat += dlat

        shift = 0
        result = 0
        while True:
            b = ord(polyline[index]) - 63
            index += 1
            result |= (b & 0x1f) << shift
            shift += 5
            if b < 0x20:
                break
        dlng = ~(result >> 1) if (result & 1) else (result >> 1)
        lng += dlng

        coords.append((lng / 1e5, lat / 1e5))

    return coords


def fetch_route(api_key: str, origin, destination):
    url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {
        "origin": f"{origin['lat']},{origin['lon']}",
        "destination": f"{destination['lat']},{destination['lon']}",
        "mode": "driving",
        "departure_time": "now",
        "key": api_key,
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get('status') != 'OK':
        raise RuntimeError(f"Directions API status={data.get('status')}; error={data.get('error_message')}")
    route = data['routes'][0]
    leg = route['legs'][0]
    poly = route['overview_polyline']['points']

    distance_km = round(leg['distance']['value'] / 1000.0, 1)
    duration_min = round(leg['duration']['value'] / 60.0)
    duration_traffic_min = None
    if 'duration_in_traffic' in leg:
        duration_traffic_min = round(leg['duration_in_traffic']['value'] / 60.0)

    delay_min = None
    if duration_traffic_min is not None:
        delay_min = max(0, duration_traffic_min - duration_min)

    coords = decode_polyline(poly)
    return {
        "coords": coords,
        "distance_km": distance_km,
        "duration_min": duration_min,
        "duration_traffic_min": duration_traffic_min,
        "delay_min": delay_min,
    }


def main():
    api_key = os.environ.get('GOOGLE_MAPS_API_KEY')
    if not api_key:
        raise SystemExit('GOOGLE_MAPS_API_KEY env var is required')

    features = []
    for r in ROUTES:
        rr = fetch_route(api_key, r['origin'], r['destination'])
        props = {
            "route_id": r['route_id'],
            "name": r['name'],
            "origin": r['origin']['name'],
            "destination": r['destination']['name'],
            "distance_km": rr['distance_km'],
            "duration_min": rr['duration_min'],
            "duration_traffic_min": rr['duration_traffic_min'],
            "delay_min": rr['delay_min'],
            "risk_note": r.get('risk_note'),
            "line_color": r.get('line_color'),
            "last_updated_utc": datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
            "source": "Google Directions API",
        }
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": rr['coords']},
            "properties": props,
        })

    out = {
        "type": "FeatureCollection",
        "name": "Gulf AOR Ground Routes",
        "description": "Primary overland transit routes — Dubai, Doha, Bahrain to Muscat and Riyadh.",
        "features": features,
    }

    out_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'geo', 'ground_routes.geojson')
    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w') as f:
        json.dump(out, f, ensure_ascii=False)

    print(f"Wrote {out_path} ({len(features)} routes)")


if __name__ == '__main__':
    main()
