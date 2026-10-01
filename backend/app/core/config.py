"""Single source for project paths and .env loading.

Configuration comes from the repository-root `.env`. Environment variables
set by the shell, CI, or the server always win (override=False).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[3]

load_dotenv(ROOT_DIR / ".env", override=False)

DATA_DIR = ROOT_DIR / "data"
FIXTURE_DIR = Path(os.getenv("SUPPORTAI_FIXTURE_DIR", str(DATA_DIR / "fixtures")))
RUNTIME_DIR = Path(os.getenv("SUPPORTAI_RUNTIME_DIR", str(DATA_DIR / "runtime")))
