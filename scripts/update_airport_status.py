#!/usr/bin/env python3
"""
update_airport_status.py
Single source of truth for airport status updates.
Updates airports.json AND airports.geojson in lockstep.

Usage:
    python3 scripts/update_airport_status.py DXB OPEN
    python3 scripts/update_airport_status.py BAH CLOSED "No timeline; monitor BCAA"
    python3 scripts/update_airport_status.py DOH OBSTRUCTED "Partial ops resumed"

Status values:
    OPEN        Green  (#2ea043) — Operating, some cancellations acceptable
    OBSTRUCTED  Amber  (#f0a500) — Limited ops / most intl cancelled / not fully shut
    CLOSED      Red    (#f85149) — Fully suspended, no commercial service
"""

import json, os, sys
from datetime import datetime, timezone

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AIRPORTS_F = os.path.join(BASE_DIR, 'data', 'airports.json')
GEO_F      = os.path.join(BASE_DIR, 'data', 'geo', 'airports.geojson')

STATUS_MAP = {
    "OPEN":       {"code": 1, "color": "#2ea043", "icon": "circle-green", "label": "Open",       "symbol": "esriSMSCircle", "marker-color": "#2ea043", "marker-size": "medium", "marker-symbol": "airport"},
    "OBSTRUCTED": {"code": 2, "color": "#f0a500", "icon": "circle-amber", "label": "Obstructed", "symbol": "esriSMSCircle", "marker-color": "#f0a500", "marker-size": "medium", "marker-symbol": "airport"},
    "CLOSED":     {"code": 3, "color": "#f85149", "icon": "circle-red",   "label": "Closed",     "symbol": "esriSMSX",      "marker-color": "#f85149", "marker-size": "medium", "marker-symbol": "airport"},
}


def set_airport_status(iata: str, status: str, notes: str = None, airspace: str = None):
    iata   = iata.upper().strip()
    status = status.upper().strip()

    if status not in STATUS_MAP:
        print(f"ERROR: invalid status '{status}'. Must be OPEN, OBSTRUCTED, or CLOSED.")
        return False

    meta = STATUS_MAP[status]
    NOW  = datetime.now(timezone.utc).isoformat()

    # ── airports.json ────────────────────────────────────────────────────────
    airports = json.load(open(AIRPORTS_F))
    found_j  = False
    for group in airports:
        for ap in group['airports']:
            if ap['iata'] == iata:
                old_status = ap.get('status', '?')
                ap['status']       = status
                ap['status_code']  = meta['code']
                ap['marker_color'] = meta['color']
                ap['icon_type']    = meta['icon']
                ap['status_label'] = meta['label']
                ap['last_updated'] = NOW
                if notes:    ap['notes']    = notes
                if airspace: ap['airspace'] = airspace
                found_j = True
                print(f"airports.json  {iata}: {old_status} → {status}  color={meta['color']}")
    if not found_j:
        print(f"WARNING: {iata} not found in airports.json")

    with open(AIRPORTS_F, 'w') as f:
        json.dump(airports, f, indent=2)

    # ── airports.geojson ─────────────────────────────────────────────────────
    geo     = json.load(open(GEO_F))
    found_g = False
    for feat in geo['features']:
        p = feat['properties']
        if p['iata'] == iata:
            old_status = p.get('status', '?')
            p['status']         = status
            p['status_code']    = meta['code']
            p['marker_color']   = meta['color']
            p['icon_type']      = meta['icon']
            p['status_label']   = meta['label']
            p['marker-color']   = meta['marker-color']   # simplestyle — ArcGIS reads directly
            p['marker-size']    = meta['marker-size']
            p['marker-symbol']  = meta['marker-symbol']
            p['last_updated']   = NOW
            if notes:    p['notes']    = notes
            if airspace: p['airspace'] = airspace
            found_g = True
            print(f"airports.geojson {iata}: {old_status} → {status}  color={meta['color']}")

    if not found_g:
        print(f"WARNING: {iata} not found in airports.geojson")

    with open(GEO_F, 'w') as f:
        json.dump(geo, f, indent=2)

    return found_j and found_g


def audit():
    """Print current status of all airports and flag any color mismatches."""
    airports = json.load(open(AIRPORTS_F))
    geo      = json.load(open(GEO_F))
    geo_map  = {f['properties']['iata']: f['properties'] for f in geo['features']}

    print(f"\n{'IATA':<6} {'Status':<12} {'Color':<10} {'Code'} {'GeoJSON Match'}")
    print("-" * 55)
    all_ok = True
    for group in airports:
        for ap in group['airports']:
            iata   = ap['iata']
            status = ap.get('status', '?')
            color  = ap.get('marker_color', '?')
            code   = ap.get('status_code', '?')
            exp    = STATUS_MAP.get(status, {})
            gp     = geo_map.get(iata, {})
            geo_ok = (gp.get('status') == status and
                      gp.get('marker_color') == exp.get('color') and
                      gp.get('status_code') == exp.get('code'))
            color_ok = (color == exp.get('color') and code == exp.get('code'))
            ok = geo_ok and color_ok
            flag = '✅' if ok else '❌'
            if not ok: all_ok = False
            print(f"  {flag} {iata:<6} {status:<12} {color:<10} {code}   geo={'✅' if geo_ok else '❌'}")

    if all_ok:
        print("\n✅ All airports consistent — JSON, GeoJSON, and colors aligned.")
    else:
        print("\n❌ Mismatches found. Run with --fix to repair.")
    return all_ok


def fix_all():
    """Re-apply correct color/code/icon to every airport based on its status field."""
    airports = json.load(open(AIRPORTS_F))
    geo      = json.load(open(GEO_F))
    geo_map  = {f['properties']['iata']: f['properties'] for f in geo['features']}
    NOW      = datetime.now(timezone.utc).isoformat()
    fixed    = 0

    for group in airports:
        for ap in group['airports']:
            status = ap.get('status')
            meta   = STATUS_MAP.get(status)
            if not meta: continue
            ap['status_code']  = meta['code']
            ap['marker_color'] = meta['color']
            ap['icon_type']    = meta['icon']
            ap['status_label'] = meta['label']
            # Sync to GeoJSON
            gp = geo_map.get(ap['iata'])
            if gp:
                gp['status']       = status
                gp['status_code']  = meta['code']
                gp['marker_color'] = meta['color']
                gp['icon_type']    = meta['icon']
                gp['status_label'] = meta['label']
            fixed += 1

    with open(AIRPORTS_F, 'w') as f:
        json.dump(airports, f, indent=2)
    with open(GEO_F, 'w') as f:
        json.dump(geo, f, indent=2)
    print(f"Fixed {fixed} airports — all colors realigned.")


if __name__ == '__main__':
    args = sys.argv[1:]
    if not args or args[0] == '--audit':
        audit()
    elif args[0] == '--fix':
        fix_all()
        audit()
    elif len(args) >= 2:
        iata   = args[0]
        status = args[1]
        notes  = args[2] if len(args) > 2 else None
        set_airport_status(iata, status, notes)
    else:
        print(__doc__)
