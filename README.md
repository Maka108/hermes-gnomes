# Hermes Gnomes

Autopilot agent for the gnome-statues business. Safety primitives library (Phase 0B).

Part of the Hermes multi-business autopilot system. See the design spec in the `hermes-planning` repo:
`docs/superpowers/specs/2026-04-13-hermes-multi-business-design.md`

## Quick start (WSL2 or Windows development)

```bash
cd ~/code/hermes-gnomes  # or c:\Users\maka\code\hermes-gnomes on Windows
uv sync --all-extras
uv run pytest -v
uv run ruff check src tests
```

## What this repo contains

Phase 0B safety primitives:
- `config.py` — pydantic config loader
- `untrusted.py` — prompt injection defense (wrap + scan + leak check)
- `secrets_vault.py` — age-backed secrets loader
- `customer_db.py` — SQLite schema and CRUD (customers, orders, campaigns, unsubscribes, approval_queue, cost_events, rate_limit_state, image_assets)
- `rate_limiter.py` — per-tool windowed throttle (per_minute + per_day)
- `decision_log.py` — append-only decision log
- `cost_tracker.py` — per-call cost event log with daily totals and rolling baseline
- `anomaly_detector.py` — 7-day baseline comparison with configurable multiplier
- `approval_queue.py` — SQLite queue with 3h/6h re-ping, persistent, no auto-reject
- `telegram_bridge.py` — stub with untrusted wrapping (real send in Phase 1)
- `gdrive_reader.py` — Google Drive product photo sync (mockable protocol)

## What this repo does NOT contain

- Phase 1+ Hermes skills (etsy-listing-writer, etc.) — coming next
- Real Telegram / Etsy / Instagram / Pinterest / TikTok API clients
- VPS provisioning runbook (separate Phase 0A plan)

## Manual Google Drive smoke test (post-plan)

The `GDriveReader` tests use a `FakeDriveClient`. To smoke test the real
`GoogleDriveClient` end-to-end, you need:

1. A Google Cloud service account JSON key with Drive read scope
2. A Google Drive folder ID the service account has been shared on
3. Environment variables:
   - `GOOGLE_SERVICE_ACCOUNT_JSON_PATH`
   - `GOOGLE_DRIVE_FOLDER_ID`

Then run:
```bash
uv run python -c "
import os
from pathlib import Path
from hermes_gnomes.customer_db import init_db
from hermes_gnomes.gdrive_reader import GDriveReader, GoogleDriveClient

db = Path('/tmp/gdrive_smoke.db')
init_db(db)
client = GoogleDriveClient(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON_PATH'])
reader = GDriveReader(
    drive_client=client,
    folder_id=os.environ['GOOGLE_DRIVE_FOLDER_ID'],
    local_dir=Path('/tmp/gdrive_smoke_images'),
    db_path=db,
)
synced = reader.sync_folder()
print(f'Synced {len(synced)} image(s).')
for f in synced:
    print(f'  - {f.filename} ({f.bytes_size} bytes)')
"
```

## Status

Phase 0B complete when:
- [x] `uv run pytest` → all tests pass
- [x] `uv run ruff check src tests` → clean
- [ ] Manual gdrive smoke test above runs successfully against a real folder

Phase 0A (VPS provisioning) is a separate plan and lives in `hermes-planning`.
