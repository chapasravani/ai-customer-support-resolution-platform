import os
from pathlib import Path

from backend.app.infrastructure import db
from backend.app.workflows.support_agent.tools import business_actions


def test_r21_file_store_and_action_paths_are_test_local():
    repo = Path(__file__).resolve().parents[3]
    configured_db = Path(os.environ["SUPPORTAI_DATA_FILE"]).resolve()
    configured_fixtures = Path(os.environ["SUPPORTAI_FIXTURE_DIR"]).resolve()

    assert db.DATA_FILE.resolve() == configured_db
    assert configured_db.is_relative_to(repo) is False
    assert business_actions.FIXTURE_DATA.resolve() == configured_fixtures
    assert business_actions.FIXTURE_DATA.resolve().is_relative_to(repo / "backend.app.workflows.support_agent" / "data") is False
    assert business_actions.DATA.resolve().is_relative_to(repo / "backend.app.workflows.support_agent" / "data") is False
