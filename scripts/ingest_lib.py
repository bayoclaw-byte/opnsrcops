#!/usr/bin/env python3
"""
ingest_lib.py — durable data plumbing for the Gulf AOR dashboard.

This module is the "doesn't die" layer. It gives the fetchers and the
orchestrator three guarantees that the original scripts lacked:

  1. ATOMIC WRITES        — a file is never left half-written. We write to a
                            temp file, fsync, then os.replace() (atomic on
                            POSIX). A process killed mid-write leaves the old
                            good file intact instead of a truncated/corrupt one.

  2. NEVER-THROW READS     — safe_load_json() returns a default instead of
                            raising on a missing/corrupt file, so one bad file
                            can never 500 the whole dashboard.

  3. PER-SOURCE STATUS     — every ingestion job records last_success,
                            last_error, duration, and freshness to
                            data/ingest_status.json. Staleness becomes visible
                            instead of silent.

It deliberately has no third-party dependencies (stdlib only) so it can always
import, even if `requests` or anything else is missing.
"""

import json
import os
import sys
import time
import tempfile
import traceback
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
STATUS_FILE = os.path.join(DATA_DIR, 'ingest_status.json')


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def log(msg):
    """Single-line timestamped log to stdout, flushed (journald/cron friendly)."""
    print(f'[{now_iso()}] {msg}', flush=True)


# ── Atomic write ────────────────────────────────────────────────────────────
def atomic_write_text(path, text, newline=''):
    """Write `text` to `path` atomically (temp file + fsync + os.replace).

    A process killed mid-write leaves the old good file intact rather than a
    truncated one. os.replace() is atomic on POSIX.
    """
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)

    fd, tmp = tempfile.mkstemp(prefix='.tmp-', dir=directory)
    try:
        with os.fdopen(fd, 'w', newline=newline) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        # Clean up the temp file on any failure; never leave litter behind.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def atomic_write_json(path, data, indent=2, ensure_ascii=True):
    """Serialize `data` and write it to `path` atomically.

    The data is fully serialized to a string FIRST — so if serialization
    fails, the existing file on disk is left untouched (we never open the
    target for writing on a bad payload).
    """
    text = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii)
    return atomic_write_text(path, text)


# ── Resilient read ───────────────────────────────────────────────────────────
def safe_load_json(path, default=None):
    """Load JSON from `path`, returning `default` on ANY failure.

    Missing file, corrupt JSON, permission error — all degrade to `default`
    and a log line, instead of propagating an exception to a web request.
    """
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception as e:
        log(f'WARN safe_load_json({os.path.relpath(path, BASE_DIR)}): {e}')
        return default


# ── Status tracking ───────────────────────────────────────────────────────────
def load_status():
    return safe_load_json(STATUS_FILE, default={}) or {}


def _write_status(status):
    try:
        atomic_write_json(STATUS_FILE, status)
    except Exception as e:
        log(f'WARN could not write status file: {e}')


def record_status(name, *, ok, duration_s, error=None, detail=None, outputs=None):
    """Merge one job's outcome into data/ingest_status.json (atomically)."""
    status = load_status()
    entry = status.get(name, {})
    ts = now_iso()

    entry['last_run'] = ts
    entry['last_duration_s'] = round(duration_s, 3)
    entry['ok'] = ok
    if detail is not None:
        entry['detail'] = detail
    if outputs is not None:
        entry['outputs'] = outputs

    if ok:
        entry['last_success'] = ts
        entry['last_error'] = None
        entry['consecutive_failures'] = 0
    else:
        entry['last_error'] = error
        entry['consecutive_failures'] = int(entry.get('consecutive_failures', 0)) + 1

    status[name] = entry
    _write_status(status)
    return entry


# ── Job model ─────────────────────────────────────────────────────────────────
class Source:
    """One ingestion source.

    fn          callable taking no args; performs the fetch + atomic write(s).
                Return value (if a dict) is stored as the job's `detail`.
    interval_s  how often the daemon should run it.
    requires    list of env var names that must be set & non-empty for the job
                to run. If any are missing the job is reported as `disabled`
                rather than failing — so a half-configured deploy still runs
                every source it CAN run.
    retries     attempts on failure within a single run (with backoff).
    """

    def __init__(self, name, fn, interval_s=900, requires=None,
                 retries=2, backoff_s=3, outputs=None):
        self.name = name
        self.fn = fn
        self.interval_s = interval_s
        self.requires = list(requires or [])
        self.retries = retries
        self.backoff_s = backoff_s
        self.outputs = list(outputs or [])

    def missing_env(self):
        return [k for k in self.requires
                if not (os.environ.get(k) or '').strip()]

    def is_due(self, status_entry):
        """True if the source has never succeeded or its interval has elapsed."""
        last = (status_entry or {}).get('last_run')
        if not last:
            return True
        try:
            last_dt = datetime.fromisoformat(last)
        except ValueError:
            return True
        age = (datetime.now(timezone.utc) - last_dt).total_seconds()
        return age >= self.interval_s


def run_source(src):
    """Run one Source in full isolation. Never raises.

    Returns a dict describing the outcome. An exception inside the source's fn
    is caught, retried per policy, recorded to the status file, and logged —
    it can never propagate out to kill the orchestrator loop.
    """
    missing = src.missing_env()
    if missing:
        log(f'SKIP {src.name}: missing env {missing} (disabled)')
        record_status(src.name, ok=False, duration_s=0.0,
                      error=f'disabled: missing env {missing}',
                      detail={'disabled': True, 'missing_env': missing},
                      outputs=src.outputs)
        return {'name': src.name, 'status': 'disabled', 'missing_env': missing}

    attempt = 0
    start_total = time.monotonic()
    last_err = None
    while attempt <= src.retries:
        attempt += 1
        t0 = time.monotonic()
        try:
            log(f'RUN  {src.name} (attempt {attempt}/{src.retries + 1})')
            detail = src.fn()
            dur = time.monotonic() - t0
            if not isinstance(detail, dict):
                detail = {'result': detail} if detail is not None else {}
            record_status(src.name, ok=True, duration_s=dur,
                          detail=detail, outputs=src.outputs)
            log(f'OK   {src.name} in {dur:.2f}s')
            return {'name': src.name, 'status': 'ok', 'duration_s': dur,
                    'detail': detail}
        except Exception as e:
            last_err = f'{type(e).__name__}: {e}'
            log(f'FAIL {src.name} attempt {attempt}: {last_err}')
            log(traceback.format_exc().rstrip())
            if attempt <= src.retries:
                time.sleep(src.backoff_s * attempt)  # linear backoff

    dur_total = time.monotonic() - start_total
    record_status(src.name, ok=False, duration_s=dur_total,
                  error=last_err, outputs=src.outputs)
    log(f'GAVE UP {src.name} after {src.retries + 1} attempts: {last_err}')
    return {'name': src.name, 'status': 'error', 'error': last_err}


def health_summary(sources, stale_grace=2.0):
    """Build a JSON-serializable health report from the status file.

    A source is `stale` if its age exceeds interval_s * stale_grace.
    Overall status is the worst of its sources: ok < stale < error/down.
    """
    status = load_status()
    by_name = {s.name: s for s in sources}
    feeds = {}
    worst = 'ok'
    rank = {'ok': 0, 'disabled': 0, 'stale': 1, 'error': 2, 'down': 3}

    names = set(by_name) | set(status)
    for name in sorted(names):
        entry = status.get(name, {})
        src = by_name.get(name)
        last_success = entry.get('last_success')
        age = None
        if last_success:
            try:
                age = (datetime.now(timezone.utc)
                       - datetime.fromisoformat(last_success)).total_seconds()
            except ValueError:
                age = None

        if (entry.get('detail') or {}).get('disabled'):
            state = 'disabled'
        elif last_success is None:
            state = 'down'
        elif not entry.get('ok', False):
            state = 'error'
        elif src and age is not None and age > src.interval_s * stale_grace:
            state = 'stale'
        else:
            state = 'ok'

        if rank.get(state, 0) > rank.get(worst, 0):
            worst = state

        feeds[name] = {
            'state': state,
            'last_success': last_success,
            'last_run': entry.get('last_run'),
            'last_error': entry.get('last_error'),
            'age_s': round(age) if age is not None else None,
            'interval_s': src.interval_s if src else None,
            'consecutive_failures': entry.get('consecutive_failures', 0),
            'outputs': entry.get('outputs', []),
        }

    return {
        'status': worst,
        'generated_utc': now_iso(),
        'feeds': feeds,
    }
