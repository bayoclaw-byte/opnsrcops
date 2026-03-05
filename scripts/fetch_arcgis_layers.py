import json, math, re, sys
from pathlib import Path
import requests

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / 'data'
GEO_DIR = DATA_DIR / 'geo'

LAYER_URLS = {
    'idf_lebanon_2026_03_04': 'https://services-eu1.arcgis.com/cOhMqNf3ihcdtO7J/arcgis/rest/services/Lebanon_Israeli_Strikes_04MARCH_XYTableToPoint/FeatureServer/0',
    'iranian_attacks_2026': 'https://services-eu1.arcgis.com/cOhMqNf3ihcdtO7J/arcgis/rest/services/IranianAttack2026/FeatureServer/0',
}


def _norm_text(s: str) -> str:
    s = (s or '').strip().lower()
    s = re.sub(r'\s+', ' ', s)
    return s


def _round_coord(x, places=4):
    if x is None:
        return None
    try:
        return round(float(x), places)
    except Exception:
        return None


def feature_signature(props: dict, geom: dict):
    # Try a few likely fields
    date = _norm_text(str(props.get('Date') or props.get('date') or props.get('DATE') or ''))
    name = _norm_text(str(props.get('Name') or props.get('name') or props.get('EVENT') or ''))
    loc = _norm_text(str(props.get('Location') or props.get('location') or props.get('PLACE') or ''))
    incident = _norm_text(str(props.get('Incident') or props.get('incident') or props.get('DESCRIPTION') or props.get('details') or ''))

    coords = None
    if geom and geom.get('type') == 'Point':
        coords = geom.get('coordinates')
    lon = lat = None
    if isinstance(coords, (list, tuple)) and len(coords) >= 2:
        lon, lat = coords[0], coords[1]
    lon = _round_coord(lon)
    lat = _round_coord(lat)

    key = '|'.join([
        date,
        name,
        loc,
        incident[:160],  # cap
        str(lat),
        str(lon),
    ])
    return key


def load_existing_signatures():
    sigs = set()

    # 1) Standardized strikes/intercepts (ours)
    std_geo = GEO_DIR / 'standardized_strikes_intercepts_v1.geojson'
    if std_geo.exists():
        fc = json.loads(std_geo.read_text())
        for f in fc.get('features', []):
            sigs.add(feature_signature(f.get('properties', {}), f.get('geometry', {})))

    # 2) StrikeMap-derived layer (ours)
    sm_geo = GEO_DIR / 'strikemap_incidents_filtered_deduped_r001.geojson'
    if sm_geo.exists():
        fc = json.loads(sm_geo.read_text())
        for f in fc.get('features', []):
            sigs.add(feature_signature(f.get('properties', {}), f.get('geometry', {})))

    # 3) Generic strike_locations (ours)
    strike_locations = GEO_DIR / 'strike_locations.geojson'
    if strike_locations.exists():
        fc = json.loads(strike_locations.read_text())
        for f in fc.get('features', []):
            sigs.add(feature_signature(f.get('properties', {}), f.get('geometry', {})))

    return sigs


def fetch_geojson(layer_base_url: str):
    url = layer_base_url.rstrip('/') + '/query'
    params = {
        'where': '1=1',
        'outFields': '*',
        'f': 'geojson',
        'resultRecordCount': 2000,
        'returnGeometry': 'true',
    }
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def main():
    existing = load_existing_signatures()

    GEO_DIR.mkdir(parents=True, exist_ok=True)

    out = {}
    for key, base in LAYER_URLS.items():
        fc = fetch_geojson(base)
        feats = fc.get('features', [])
        kept = []
        dropped = 0
        seen = set()
        for f in feats:
            sig = feature_signature(f.get('properties', {}), f.get('geometry', {}))
            if sig in seen:
                dropped += 1
                continue
            seen.add(sig)
            if sig in existing:
                dropped += 1
                continue
            kept.append(f)
        fc['features'] = kept
        out[key] = {
            'total': len(feats),
            'kept_new': len(kept),
            'dropped_dupe_or_existing': dropped,
        }
        (GEO_DIR / f'{key}_deduped.geojson').write_text(json.dumps(fc))

    print(json.dumps(out, indent=2))


if __name__ == '__main__':
    main()
