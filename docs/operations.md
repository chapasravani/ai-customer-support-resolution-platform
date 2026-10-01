# Operations

## Local run

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
Copy-Item .env.example .env          # then set GOOGLE_API_KEY and JWT_SECRET
python -m scripts.manage_admin create --email admin@example.com --password "UseAUniquePassword123!" --name "Support Admin"
python -m uvicorn backend.app.main:app --reload --port 8000
python -m http.server 3000 --directory frontend/demo-customer
python -m http.server 3001 --directory frontend/admin
```

## Configuration

`backend/app/core/config.py` is the only place that loads `.env` and defines data paths. Real environment variables always win over `.env` (`override=False`).

## Data locations

| Path | Tracked | Contents |
|---|---|---|
| `data/fixtures/` | yes | Read-only sample customers, orders, policies |
| `data/runtime/actions.json` | no | Recorded refund/replacement/cancellation requests |
| `data/runtime/db_store.json` | no | Local file-backed store when MongoDB is unreachable |
| `data/runtime/chroma_db/` | no | Chroma policy vector index |

The file-backed store is single-process: its lock only coordinates threads in one Python process. Stop the API before running `scripts/manage_admin.py` against it. Use MongoDB for any shared deployment.

## Tests and CI

`py -3.12 -m pytest -q` runs the full suite with stub models and temporary stores; no API keys are needed. The suite fails if any tracked file under `data/` changes. CI (`.github/workflows/ci.yml`) runs the same command on Python 3.12.
