#!/usr/bin/env python3
"""
ingest.py — set-and-forget data plumbing for the Gulf AOR dashboard.

This is the orchestrator bamqam-style: it pulls from every configured feed on a
schedule, writes the data the map reads, and DOES NOT DIE when a single source
fails. Each source runs in full isolation (caught exceptions, retries, atomic
writes), and per-source freshness is recorded to data/ingest_status.json so the
web layer can surface staleness instead of silently rotting.

Usage:
    python3 scripts/ingest.py --once         # run every due source once (cron)
    python3 scripts/ingest.py --once --all    # force-run every source now
    python3 scripts/ingest.py --daemon        # run forever (systemd / nohup)
    python3 scripts/ingest.py --list          # print the source registry
    python3 scripts/ingest.py --status        # print current freshness report

Sources whose required env vars are absent are reported as `disabled` and
skipped — a half-configured deploy still runs every feed it CAN run.

Configuration via env:
    GOOGLE_MAPS_API_KEY   border status + ground routes
    FR24_API_KEY          live flight attribution
    INGEST_TICK_SECONDS   daemon poll interval (default 60)
"""

import argparse
import importlib
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest_lib import Source, run_source, health_summary, load_status, log, now_iso


# ── Source registry ───────────────────────────────────────────────────────────
# Each fetcher exposes a module-level main() that performs its fetch + atomic
# write and returns a small detail dict. We wrap them as isolated Sources.
def _job(module_name):
    """Import a fetcher module lazily and return its main() as a callable.

    Imported lazily inside the job so an import-time error in one fetcher (e.g.
    a missing optional dependency) is caught by run_source and recorded as that
    source's failure — it never stops the others from importing or running.
    """
    def run():
        mod = importlib.import_module(module_name)
        importlib.reload(mod)  # pick up edits without restarting a long daemon
        return mod.main()
    return run


def build_sources():
    return [
        Source(
            name='border_status',
            fn=_job('fetch_border_status'),
            interval_s=30 * 60,            # borders refresh every 30 min
            requires=['GOOGLE_MAPS_API_KEY'],
            outputs=['data/borders.json',
                     'data/geo/border_crossings.geojson',
                     'data/geo/gulf_aor_all_layers.csv'],
        ),
        Source(
            name='ground_routes',
            fn=_job('gen_ground_routes'),
            interval_s=60 * 60,            # routes hourly
            requires=['GOOGLE_MAPS_API_KEY'],
            outputs=['data/geo/ground_routes.geojson'],
        ),
        Source(
            name='fr24_flights',
            fn=_job('fetch_fr24'),
            interval_s=15 * 60,            # flights every 15 min (rate-limited API)
            requires=['FR24_API_KEY'],
            outputs=['data/airports.json',
                     'data/geo/airports.geojson',
                     'data/fr24_meta.json',
                     'data/fr24_airport_counts.json'],
        ),
        Source(
            name='arcgis_layers',
            fn=_job('fetch_arcgis_layers'),
            interval_s=60 * 60,            # kinetic layers hourly
            requires=[],                   # public ArcGIS endpoints; no key
            outputs=['data/geo/idf_lebanon_2026_03_04_deduped.geojson',
                     'data/geo/iranian_attacks_2026_deduped.geojson'],
        ),
    ]


# ── Run modes ──────────────────────────────────────────────────────────────────
def run_once(sources, force_all=False):
    status = load_status()
    ran, skipped = [], []
    for src in sources:
        if force_all or src.is_due(status.get(src.name)):
            run_source(src)          # never raises
            ran.append(src.name)
        else:
            skipped.append(src.name)
    if skipped:
        log(f'not due (skipped): {skipped}')
    return ran


_STOP = {'flag': False}


def _handle_signal(signum, frame):
    log(f'received signal {signum}; finishing current cycle then exiting')
    _STOP['flag'] = True


def run_daemon(sources, tick_seconds):
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    log(f'ingest daemon up; {len(sources)} sources; tick={tick_seconds}s')
    log('sources: ' + ', '.join(f'{s.name}@{s.interval_s}s' for s in sources))

    # Wrap the whole loop so an unexpected error in scheduling logic (not a
    # source — those are already isolated) cannot take the daemon down.
    while not _STOP['flag']:
        try:
            run_once(sources, force_all=False)
        except Exception as e:  # pragma: no cover - belt and suspenders
            log(f'ERROR in scheduler loop (continuing): {type(e).__name__}: {e}')
        # Sleep in short slices so SIGTERM is honored promptly.
        slept = 0
        while slept < tick_seconds and not _STOP['flag']:
            time.sleep(min(2, tick_seconds - slept))
            slept += 2
    log('ingest daemon stopped cleanly')


# ── CLI ────────────────────────────────────────────────────────────────────────
def main(argv=None):
    p = argparse.ArgumentParser(description='Gulf AOR ingestion orchestrator')
    p.add_argument('--once', action='store_true', help='run due sources once and exit')
    p.add_argument('--all', action='store_true', help='with --once, force-run all sources')
    p.add_argument('--daemon', action='store_true', help='run forever on a schedule')
    p.add_argument('--list', action='store_true', help='list the source registry')
    p.add_argument('--status', action='store_true', help='print freshness report')
    args = p.parse_args(argv)

    sources = build_sources()

    if args.list:
        for s in sources:
            miss = s.missing_env()
            state = f'DISABLED (missing {miss})' if miss else 'enabled'
            print(f'{s.name:16s} every {s.interval_s:5d}s  {state}')
            for o in s.outputs:
                print(f'                  -> {o}')
        return 0

    if args.status:
        import json
        print(json.dumps(health_summary(sources), indent=2))
        return 0

    if args.daemon:
        tick = int(os.environ.get('INGEST_TICK_SECONDS', '60'))
        run_daemon(sources, tick)
        return 0

    if args.once:
        ran = run_once(sources, force_all=args.all)
        log(f'once complete; ran: {ran or "(none due)"}')
        return 0

    p.print_help()
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
