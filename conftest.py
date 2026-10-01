import os
import shutil
import subprocess
import tempfile
from pathlib import Path
import pytest

# Set the file-backed stores before test modules import the application.
_test_data_root = Path(tempfile.mkdtemp(prefix="supportai-tests-"))
os.environ["SUPPORTAI_DATA_FILE"] = str(_test_data_root / "db_store.json")
_customer_data = _test_data_root / "customer_data"
_runtime_data = _test_data_root / "runtime_data"
_customer_data.mkdir()
_runtime_data.mkdir()
_sample_data = Path(__file__).parent / "data" / "fixtures"
for _filename in ("customers.json", "orders.json", "policies.json", "support_cases.json"):
    if (_sample_data / _filename).exists():
        shutil.copy2(_sample_data / _filename, _customer_data / _filename)
os.environ["SUPPORTAI_FIXTURE_DIR"] = str(_customer_data)
os.environ["SUPPORTAI_RUNTIME_DIR"] = str(_runtime_data)

# Ensure a cryptographically strong 32+ character JWT secret is set for test sessions
if not os.environ.get("JWT_SECRET") or len(os.environ["JWT_SECRET"]) < 32 or os.environ["JWT_SECRET"] == "dev-only-secret-change-me":
    os.environ["JWT_SECRET"] = "test-secret-must-be-at-least-32-chars-long-secure-random"


@pytest.fixture(autouse=True)
def isolate_sample_data(tmp_path, monkeypatch):
    """Ensure no test writes to tracked sample data in data/ (Phase 6)."""
    try:
        from backend.app.workflows.support_agent.tools import business_actions
        repo_data = business_actions.FIXTURE_DATA
        if repo_data.exists():
            for filename in ["orders.json", "policies.json"]:
                src = repo_data / filename
                if src.exists():
                    shutil.copy(src, tmp_path / filename)
            (tmp_path / "actions.json").write_text("{}", encoding="utf-8")
            (tmp_path / "support_cases.json").write_text("{}", encoding="utf-8")
            monkeypatch.setattr(business_actions, "DATA", tmp_path)
    except ImportError:
        pass


def _data_worktree_state():
    paths = ["data"]
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", *paths],
        capture_output=True, text=True, check=False,
    )
    diff = subprocess.run(
        ["git", "diff", "--binary", "--", *paths],
        capture_output=True, check=False,
    )
    return status.stdout, diff.stdout


def pytest_configure(config):
    config._data_state_before = _data_worktree_state()


def pytest_sessionfinish(session, exitstatus):
    current = _data_worktree_state()
    if current != session.config._data_state_before:
        print("\nRuntime data changed while tests were running.")
        session.exitstatus = 1
