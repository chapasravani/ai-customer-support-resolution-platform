"""Single source for project paths and .env loading.

Environment variables set by the shell, CI, or the server always win
(override=False). The root `.env` is the supported location; `backend/.env`
and `final_customer_support/.env` are still read so existing local setups
keep working until they are merged into the root file.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[3]

for _env in (ROOT_DIR / ".env", ROOT_DIR / "backend" / ".env", ROOT_DIR / "final_customer_support" / ".env"):
    if _env.exists():
        load_dotenv(_env, override=False)

DATA_DIR = ROOT_DIR / "data"
FIXTURE_DIR = Path(os.getenv("SUPPORTAI_FIXTURE_DIR", str(DATA_DIR / "fixtures")))
RUNTIME_DIR = Path(os.getenv("SUPPORTAI_RUNTIME_DIR", str(DATA_DIR / "runtime")))
