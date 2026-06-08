#!/usr/bin/env python3
"""Export every collected (or collectable) event into one canonical store.

The opnsrcops suite accumulates "events" in several places, each with its own
schema:

  * data/activity.json                              — narrative activity feed
                                                      (also where /api/admin/event writes)
  * data/geo/standardized_strikes_intercepts_v1.geojson
                                                    — standardized strikes/intercepts
  * data/geo/strikes_master.geojson                 — StrikeMap-derived kinetic events

This script ingests all of them, normalizes each record into a single canonical
schema, dedupes, and publishes the result to a canonical database plus flat-file
exports that future GIS suites can pull from:

  data/canonical/events.db        — SQLite, the canonical source of truth
  data/canonical/events.geojson   — canonical layer (records with coordinates)
  data/canonical/events.csv       — canonical table (all records)
  data/canonical/events.json      — canonical records as a JSON array
  data/canonical/manifest.json    — generation metadata + source breakdown

Stdlib only — no third-party dependencies. Idempotent: re-running regenerates
the store from source, upserting on canonical event_id.

Usage:
    python3 scripts/export_canonical_events.py            # full export
    python3 scripts/export_canonical_events.py --stats    # print counts only
"""
import argparse
import csv
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
GEO_DIR = os.path.join(DATA_DIR, 'geo')
CANONICAL_DIR = os.path.join(DATA_DIR, 'canonical')

SCHEMA_VERSION = 1

# Canonical column order — used for the SQLite table, CSV header, and JSON keys.
COLUMNS = [
    'event_id',            # canonical primary key (stable across runs)
    'source_dataset',      # activity_feed | standardized_v1 | strikemap_master
    'source_id',           # original id within the source store
    'event_kind',          # strike | intercept | mixed | launch | explosion | activity | other
    'category',            # free-form classifier from source
    'title',
    'summary',
    'datetime_utc',        # ISO-8601
    'date',                # YYYY-MM-DD
    'countries',           # JSON array of normalized country slugs
    'target_country',
    'target_name',
    'attacker',
    'weapon',
    'severity',            # critical | high | medium | low | None
    'outcome',
    'side',                # attributed side (iran / israel / us / ...)
    'lat',
    'lon',
    'geo_precision',
    'casualties_killed',
    'casualties_injured',
    'interceptions_claimed',
    'source',              # provenance label
    'source_url',
    'classification',
    'content_hash',        # de-dup fingerprint (per source_dataset)
    'ingested_at',
    'raw',                 # original record as a JSON blob
]

# Country normalization → slug used elsewhere in the suite.
COUNTRY_SLUG = {
    'uae': 'uae', 'united arab emirates': 'uae', 'u.a.e.': 'uae',
    'saudi': 'saudi', 'saudi arabia': 'saudi', 'ksa': 'saudi',
    'bahrain': 'bahrain',
    'qatar': 'qatar',
    'oman': 'oman',
    'kuwait': 'kuwait',
    'lebanon': 'lebanon',
    'iran': 'iran',
    'israel': 'israel',
    'iraq': 'iraq',
    'macro': 'macro',
}


def slugify_country(value):
    if not value:
        return None
    return COUNTRY_SLUG.get(str(value).strip().lower(), str(value).strip().lower())


def _int_or_none(value):
    try:
        if value in (None, '', 'null'):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float_or_none(value):
    try:
        if value in (None, '', 'null'):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _date_from_dt(dt, fallback=None):
    if dt and len(dt) >= 10:
        return dt[:10]
    return fallback


def _content_hash(dataset, datetime_utc, title, target, lat, lon, kind):
    """Fingerprint used to collapse exact duplicates within a source dataset."""
    parts = [
        dataset or '',
        (datetime_utc or '')[:16],
        (title or '').strip().lower()[:80],
        (target or '').strip().lower()[:80],
        f'{lat:.4f}' if isinstance(lat, float) else '',
        f'{lon:.4f}' if isinstance(lon, float) else '',
        kind or '',
    ]
    return hashlib.sha1('|'.join(parts).encode('utf-8')).hexdigest()[:16]


def _blank_record():
    return {col: None for col in COLUMNS}


# ── Source loaders ─────────────────────────────────────────────────────────────
def load_activity_feed(now_iso):
    """data/activity.json — narrative activity feed (incl. admin-added events)."""
    path = os.path.join(DATA_DIR, 'activity.json')
    if not os.path.exists(path):
        return []
    with open(path) as f:
        rows = json.load(f)

    out = []
    for e in rows:
        rec = _blank_record()
        sid = e.get('id') or ''
        dt = e.get('ts_utc') or e.get('timestamp_utc')
        countries = [slugify_country(c) for c in (e.get('countries') or []) if c]
        if not countries and e.get('country'):
            countries = [slugify_country(e['country'])]
        rec.update({
            'source_dataset': 'activity_feed',
            'source_id': sid,
            'event_kind': e.get('category') or 'activity',
            'category': e.get('category'),
            'title': e.get('title'),
            'summary': e.get('summary'),
            'datetime_utc': dt,
            'date': _date_from_dt(dt),
            'countries': json.dumps([c for c in countries if c]),
            'severity': (e.get('severity') or '').lower() or None,
            'source': e.get('source'),
            'ingested_at': now_iso,
            'raw': json.dumps(e, ensure_ascii=False),
        })
        rec['event_id'] = f'actv:{sid}' if sid else None
        rec['content_hash'] = _content_hash(
            'activity_feed', dt, rec['title'], None, None, None, rec['event_kind'])
        if not rec['event_id']:
            rec['event_id'] = f"actv:{rec['content_hash']}"
        out.append(rec)
    return out


def _load_geojson_features(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f).get('features', [])


def load_standardized(now_iso):
    """data/geo/standardized_strikes_intercepts_v1.geojson."""
    path = os.path.join(GEO_DIR, 'standardized_strikes_intercepts_v1.geojson')
    out = []
    for feat in _load_geojson_features(path):
        p = feat.get('properties', {}) or {}
        if p.get('keep') is False:
            continue
        coords = (feat.get('geometry') or {}).get('coordinates') or [None, None]
        lon, lat = (coords + [None, None])[:2]
        lon, lat = _float_or_none(lon), _float_or_none(lat)
        dt = p.get('datetime_utc')
        target_country = p.get('target_country')
        rec = _blank_record()
        rec.update({
            'source_dataset': 'standardized_v1',
            'source_id': p.get('event_id'),
            'event_kind': p.get('event_kind') or 'unknown',
            'category': p.get('attack_type'),
            'title': p.get('description') or p.get('target_name'),
            'summary': p.get('notes'),
            'datetime_utc': dt,
            'date': p.get('date') or _date_from_dt(dt),
            'countries': json.dumps([slugify_country(target_country)] if target_country else []),
            'target_country': target_country,
            'target_name': p.get('target_name'),
            'attacker': p.get('attacker'),
            'weapon': p.get('attack_type'),
            'outcome': p.get('outcome_raw'),
            'lat': lat,
            'lon': lon,
            'geo_precision': p.get('geo_precision'),
            'casualties_killed': _int_or_none(p.get('casualties_killed')),
            'casualties_injured': _int_or_none(p.get('casualties_injured')),
            'interceptions_claimed': _int_or_none(p.get('interceptions_claimed')),
            'source': p.get('source_name'),
            'source_url': p.get('source_detail'),
            'ingested_at': now_iso,
            'raw': json.dumps(p, ensure_ascii=False),
        })
        rec['content_hash'] = _content_hash(
            'standardized_v1', dt, rec['title'], rec['target_name'], lat, lon, rec['event_kind'])
        sid = p.get('event_id')
        rec['source_id'] = sid
        rec['event_id'] = f'std1:{sid}' if sid else f"std1:{rec['content_hash']}"
        out.append(rec)
    return out


def load_strikemap_master(now_iso):
    """data/geo/strikes_master.geojson — StrikeMap-derived kinetic events."""
    path = os.path.join(GEO_DIR, 'strikes_master.geojson')
    out = []
    for feat in _load_geojson_features(path):
        p = feat.get('properties', {}) or {}
        coords = (feat.get('geometry') or {}).get('coordinates') or [None, None]
        lon, lat = (coords + [None, None])[:2]
        lon, lat = _float_or_none(lon), _float_or_none(lat)
        dt = p.get('datetime_utc')
        rec = _blank_record()
        country = p.get('country')
        rec.update({
            'source_dataset': 'strikemap_master',
            'source_id': p.get('event_id'),
            'event_kind': p.get('event_kind') or 'strike',
            'category': p.get('target_type'),
            'title': p.get('title'),
            'summary': p.get('location'),
            'datetime_utc': dt,
            'date': p.get('date') or _date_from_dt(dt),
            'countries': json.dumps([slugify_country(country)] if country else []),
            'target_country': country,
            'target_name': p.get('location'),
            'attacker': p.get('attributed_side') or p.get('side'),
            'weapon': p.get('weapon'),
            'side': p.get('attributed_side') or p.get('side'),
            'lat': lat,
            'lon': lon,
            'geo_precision': 'point' if lat is not None else None,
            'interceptions_claimed': _int_or_none(p.get('claimed_count')),
            'source': p.get('source'),
            'source_url': p.get('source_url'),
            'classification': p.get('classification'),
            'ingested_at': now_iso,
            'raw': json.dumps(p, ensure_ascii=False),
        })
        rec['content_hash'] = _content_hash(
            'strikemap_master', dt, rec['title'], rec['target_name'], lat, lon, rec['event_kind'])
        sid = p.get('event_id')
        rec['event_id'] = f'smap:{sid}' if sid else f"smap:{rec['content_hash']}"
        out.append(rec)
    return out


SOURCES = [
    ('activity_feed', load_activity_feed),
    ('standardized_v1', load_standardized),
    ('strikemap_master', load_strikemap_master),
]


# ── Canonicalization ───────────────────────────────────────────────────────────
def collect_records():
    now_iso = datetime.now(timezone.utc).isoformat()
    records, per_source = [], {}
    for name, loader in SOURCES:
        rows = loader(now_iso)
        per_source[name] = len(rows)
        records.extend(rows)

    # De-dupe: collapse exact duplicates by canonical event_id, then by
    # content_hash (catches the same event appearing twice in one source, e.g.
    # daily layers overlapping the master). Cross-source records are kept
    # distinct on purpose — they are independent observations of the AOR.
    seen_ids, seen_hashes, deduped, dropped = set(), set(), [], 0
    for rec in records:
        key = rec['event_id']
        if key in seen_ids or rec['content_hash'] in seen_hashes:
            dropped += 1
            continue
        seen_ids.add(key)
        seen_hashes.add(rec['content_hash'])
        deduped.append(rec)

    # Newest first where a timestamp exists; undated records sink to the bottom.
    deduped.sort(key=lambda r: (r['datetime_utc'] or ''), reverse=True)
    return deduped, per_source, dropped, now_iso


# ── Writers ────────────────────────────────────────────────────────────────────
def write_sqlite(records):
    path = os.path.join(CANONICAL_DIR, 'events.db')
    tmp = path + '.tmp'
    if os.path.exists(tmp):
        os.remove(tmp)
    conn = sqlite3.connect(tmp)
    try:
        cur = conn.cursor()
        cols_sql = ',\n  '.join(f'"{c}" TEXT' for c in COLUMNS)
        # lat/lon/casualties stay numeric for GIS range queries
        cols_sql = cols_sql.replace('"lat" TEXT', '"lat" REAL')
        cols_sql = cols_sql.replace('"lon" TEXT', '"lon" REAL')
        cur.execute(f'CREATE TABLE events (\n  {cols_sql},\n  PRIMARY KEY ("event_id")\n)')
        cur.execute('CREATE INDEX idx_events_date ON events(date)')
        cur.execute('CREATE INDEX idx_events_kind ON events(event_kind)')
        cur.execute('CREATE INDEX idx_events_dataset ON events(source_dataset)')
        placeholders = ','.join('?' for _ in COLUMNS)
        cur.executemany(
            f'INSERT OR REPLACE INTO events ({",".join(COLUMNS)}) VALUES ({placeholders})',
            [[rec[c] for c in COLUMNS] for rec in records],
        )
        conn.commit()
    finally:
        conn.close()
    os.replace(tmp, path)
    return path


def write_json(records):
    path = os.path.join(CANONICAL_DIR, 'events.json')
    with open(path, 'w') as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    return path


def write_csv(records):
    path = os.path.join(CANONICAL_DIR, 'events.csv')
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction='ignore')
        w.writeheader()
        for rec in records:
            w.writerow(rec)
    return path


def write_geojson(records):
    path = os.path.join(CANONICAL_DIR, 'events.geojson')
    features = []
    for rec in records:
        if rec['lat'] is None or rec['lon'] is None:
            continue
        props = {c: rec[c] for c in COLUMNS if c not in ('lat', 'lon', 'raw')}
        features.append({
            'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': [rec['lon'], rec['lat']]},
            'properties': props,
        })
    with open(path, 'w') as f:
        json.dump({'type': 'FeatureCollection', 'features': features}, f,
                  ensure_ascii=False, indent=2)
    return path, len(features)


def write_manifest(records, per_source, dropped, now_iso, geo_count):
    path = os.path.join(CANONICAL_DIR, 'manifest.json')
    by_kind, by_dataset = {}, {}
    for rec in records:
        by_kind[rec['event_kind']] = by_kind.get(rec['event_kind'], 0) + 1
        by_dataset[rec['source_dataset']] = by_dataset.get(rec['source_dataset'], 0) + 1
    dates = sorted(r['date'] for r in records if r['date'])
    manifest = {
        'schema_version': SCHEMA_VERSION,
        'generated_at': now_iso,
        'total_events': len(records),
        'duplicates_dropped': dropped,
        'geolocated_events': geo_count,
        'date_range': {'first': dates[0], 'last': dates[-1]} if dates else None,
        'source_record_counts': per_source,
        'canonical_by_dataset': by_dataset,
        'canonical_by_kind': by_kind,
        'columns': COLUMNS,
        'artifacts': {
            'sqlite': 'events.db',
            'geojson': 'events.geojson',
            'csv': 'events.csv',
            'json': 'events.json',
        },
        'pull_endpoint': '/api/events/canonical',
    }
    with open(path, 'w') as f:
        json.dump(manifest, f, indent=2)
    return path, manifest


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--stats', action='store_true',
                    help='print canonical counts without writing the store')
    args = ap.parse_args()

    os.makedirs(CANONICAL_DIR, exist_ok=True)
    records, per_source, dropped, now_iso = collect_records()

    if args.stats:
        print(f'Source records:      {per_source}')
        print(f'Canonical events:    {len(records)}')
        print(f'Duplicates dropped:  {dropped}')
        return 0

    db_path = write_sqlite(records)
    write_json(records)
    write_csv(records)
    geo_path, geo_count = write_geojson(records)
    _, manifest = write_manifest(records, per_source, dropped, now_iso, geo_count)

    print(f'Canonical event store published to {CANONICAL_DIR}')
    print(f'  source records:     {per_source}')
    print(f'  canonical events:   {manifest["total_events"]}  '
          f'({manifest["geolocated_events"]} geolocated)')
    print(f'  duplicates dropped: {dropped}')
    print(f'  date range:         {manifest["date_range"]}')
    print(f'  by dataset:         {manifest["canonical_by_dataset"]}')
    print(f'  artifacts:          events.db / .geojson / .csv / .json / manifest.json')
    print(f'  pull endpoint:      {manifest["pull_endpoint"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
