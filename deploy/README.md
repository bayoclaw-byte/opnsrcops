# Gulf AOR dashboard — durable data plumbing

This is the "set-and-forget" ingestion layer modelled on how bamqam.com stays
up: feeds are pulled on a schedule into the data files the map reads, each feed
is isolated so one failure can't take down the rest, and the web layer degrades
gracefully instead of 500-ing when a file is missing or mid-write.

## The pieces

| File | Role |
|------|------|
| `scripts/ingest_lib.py` | Atomic writes, never-throw reads, per-source status. No third-party deps. |
| `scripts/ingest.py` | Orchestrator. `--once` (cron), `--daemon` (set-and-forget), `--list`, `--status`. |
| `scripts/fetch_*.py`, `gen_ground_routes.py`, `update_airport_status.py` | The feeds. Now write atomically. |
| `app.py` | Web layer. Public reads are crash-safe; `/health` + `/api/health` expose freshness. |
| `deploy/*.service` | systemd units with `Restart=always` for the web + ingest daemon. |
| `deploy/crontab.example` | Cron fallback for hosts without systemd. |

## Why opnsrcops used to die — and what changed

1. **Truncated JSON on a killed write.** Every fetcher did `open(f,'w'); json.dump()`.
   A kill mid-write left a corrupt file, and the web app's bare `json.load` then
   500-ed every route that touched it. → All writes now go through
   `atomic_write_json` (temp file + fsync + `os.replace`); reads go through
   `safe_load_json` (returns a default + logs instead of raising).
2. **No supervision.** `nohup`+pidfile with no restart, hardcoded Mac path. →
   systemd units (`Restart=always`) or the cron keep-alive.
3. **No scheduler in-repo.** Feeds depended on external cron. → `ingest.py --daemon`.
4. **One bad source aborted the run.** → Each source runs isolated with retries;
   `arcgis_layers` even tolerates a single failing layer.
5. **`debug=True` in prod, missing `requests` dep, a `NameError` in the border
   admin route.** → All fixed.

## Install (systemd, recommended)

```bash
sudo mkdir -p /opt/opnsrcops && sudo chown $USER /opt/opnsrcops
git clone <repo> /opt/opnsrcops && cd /opt/opnsrcops
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# API keys
cat > .env <<'EOF'
GOOGLE_MAPS_API_KEY=...
FR24_API_KEY=...
INGEST_TICK_SECONDS=60
EOF

# Edit User/paths in the unit files, then:
sudo cp deploy/opnsrcops-web.service deploy/opnsrcops-ingest.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now opnsrcops-web opnsrcops-ingest
```

## Operate

```bash
python3 scripts/ingest.py --list      # what's configured / disabled
python3 scripts/ingest.py --once      # run due feeds now (safe to repeat)
python3 scripts/ingest.py --once --all # force every feed now
python3 scripts/ingest.py --status    # freshness report (also at /api/health)
journalctl -u opnsrcops-ingest -f     # live ingest log
curl -s localhost:5050/api/health | jq # per-feed state: ok/stale/error/down/disabled
```

A feed with no API key configured shows as **disabled** (skipped, not failed),
so a partially-configured host still runs everything it can.

## Adding a new feed (e.g. a force/order-of-battle or activity source)

1. Write a function that fetches and writes its output with `atomic_write_json`
   (a standalone `scripts/fetch_*.py` with a `main()` returning a small detail
   dict is the established pattern).
2. Register it in `scripts/ingest.py::build_sources()` with its `interval_s`,
   any `requires=[...]` env keys, and `outputs=[...]`.

That's it — scheduling, isolation, retries, status, and `/api/health` coverage
come for free.
