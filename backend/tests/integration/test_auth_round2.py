import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.core import security
from backend.app.domains import models
from backend.app.infrastructure import db
from backend.app.main import app
from backend.app.api.routes import auth as auth_routes
from backend.app.api.schemas import TicketStatus


ROOT = Path(__file__).resolve().parents[3]
client = TestClient(app)
GENERIC_REGISTER = {
    "detail": "If this email can be registered, you can now log in."
}


@pytest.mark.parametrize("secret", [
    "replace_with_a_secure_random_string_at_least_32_chars_long",
    "your_jwt_secret_min_32_chars_here_and_long_enough",
    "changeme_please_this_is_a_long_placeholder_secret",
    "realistic-prefix-placeholder-suffix-12345678901234567890",
])
def test_r14_jwt_placeholder_secret_rejected(secret, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", secret)
    with pytest.raises(RuntimeError, match="placeholder"):
        security.get_jwt_secret()


@pytest.mark.parametrize("secret", [
    "replace_with_a_secure_random_string_at_least_32_chars_long",
    "your_jwt_secret_min_32_chars_here_and_long_enough",
    "changeme_please_this_is_a_long_placeholder_secret",
    "realistic-prefix-placeholder-suffix-12345678901234567890",
])
def test_r14_app_startup_rejects_jwt_placeholders(secret, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", secret)
    with pytest.raises(RuntimeError, match="placeholder"):
        with TestClient(app):
            pass


def test_r14_all_env_examples_leave_jwt_secret_empty():
    for path in (ROOT / ".env.example",):
        text = path.read_text(encoding="utf-8")
        assert re.search(r"^JWT_SECRET=$", text, re.MULTILINE), path
        assert 'python -c "import secrets; print(secrets.token_urlsafe(48))"' in text, path


def test_n1_existing_customer_email_is_not_linked_on_registration():
    email = "sravani@example.com"
    db.get_db().users.delete_one({"email": email})
    response = client.post("/auth/register", json={"email": email, "password": "LongEnoughPass123!", "name": "Existing customer"})
    user = models.get_user_by_email(email)
    assert response.status_code == 202
    assert user is not None
    assert "customer_id" not in user
    db.get_db().users.delete_one({"email": email})


def test_n4_two_registrations_get_distinct_customer_ids():
    first = models.create_user("n4-first@example.com", "hash", "First")
    second = models.create_user("n4-second@example.com", "hash", "Second")
    try:
        assert models.get_customer_id_for_user(first) != models.get_customer_id_for_user(second)
    finally:
        db.get_db().users.delete_many({"_id": {"$in": [first["_id"], second["_id"]]}})


def test_n7_environment_value_beats_dotenv_file(tmp_path, monkeypatch):
    from dotenv import load_dotenv

    dotenv_file = tmp_path / "test.env"
    dotenv_file.write_text("SUPPORTAI_N7_VALUE=from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("SUPPORTAI_N7_VALUE", "from-environment")
    load_dotenv(dotenv_file, override=False)
    assert os.environ["SUPPORTAI_N7_VALUE"] == "from-environment"


def test_n9_pytest_config_has_no_blanket_userwarning_ignore():
    config = (ROOT / "pytest.ini").read_text(encoding="utf-8")
    assert "ignore::UserWarning" not in config


def test_r7_chat_message_reuses_request_id_on_retry():
    script = (ROOT / "frontend/demo-customer/app.js").read_text(encoding="utf-8")
    assert "crypto.randomUUID()" in script
    assert "request_id: requestId" in script
    assert "sendMessage(requestId)" in script


def test_pr_model_defaults_are_defined_once_and_db_accessors_are_typed():
    agent_code = (ROOT / "backend/app/workflows/support_agent/agent.py").read_text(encoding="utf-8")
    main_code = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    db_code = (ROOT / "backend/app/infrastructure/db.py").read_text(encoding="utf-8")
    assert agent_code.count('DEFAULT_PRIMARY_MODEL = "gemini-3.5-flash-lite"') == 1
    assert 'DEFAULT_PRIMARY_MODEL = "gemini-3.5-flash-lite"' not in main_code
    assert "from backend.app.workflows.support_agent.agent import DEFAULT_FALLBACK_MODEL, DEFAULT_PRIMARY_MODEL" in main_code
    assert "def get_client() -> Any:" in db_code
    assert "def get_db() -> Any:" in db_code


def test_r15_registration_returns_same_generic_response_for_new_and_existing_email():
    email = "round2.generic.registration@example.com"
    payload = {"email": email, "password": "LongEnoughPass123!", "name": "Generic User"}
    with patch("backend.app.domains.models.get_user_by_email", side_effect=[None, {"_id": "existing"}]), \
         patch("backend.app.domains.models.create_user", return_value={"_id": "new-user"}) as create_user:
        first = client.post("/auth/register", json=payload)
        second = client.post("/auth/register", json=payload)

    assert first.status_code == second.status_code == 202
    assert first.json() == second.json() == GENERIC_REGISTER
    create_user.assert_called_once()


def test_r16_login_rate_limit_is_shared_across_emails_and_has_retry_after(monkeypatch):
    auth_routes.reset_login_rate_limits()
    monkeypatch.setattr(auth_routes, "LOGIN_RATE_LIMIT_IP_ATTEMPTS", 2)
    with patch("backend.app.domains.models.get_user_by_email", return_value=None):
        assert client.post("/auth/login", json={"email": "one@example.com", "password": "bad"}).status_code == 401
        assert client.post("/auth/login", json={"email": "two@example.com", "password": "bad"}).status_code == 401
        blocked = client.post("/auth/login", json={"email": "three@example.com", "password": "bad"})

    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
    auth_routes.reset_login_rate_limits()


def test_r16_expired_login_rate_limit_keys_are_pruned(monkeypatch):
    auth_routes.reset_login_rate_limits()
    auth_routes._login_attempts["ip:192.0.2.10"] = [0.0]
    auth_routes._login_attempts["email:192.0.2.10:user@example.com"] = [0.0]
    monkeypatch.setattr(auth_routes.time, "time", lambda: 1000.0)
    auth_routes._check_login_rate_limit("192.0.2.10", "next@example.com")
    assert "ip:192.0.2.10" in auth_routes._login_attempts
    assert "email:192.0.2.10:user@example.com" not in auth_routes._login_attempts
    assert len(auth_routes._login_attempts) <= 2
    auth_routes.reset_login_rate_limits()


def test_l5_api_origin_fallbacks_removed_and_shared_config_loaded():
    for app_name in ("demo-customer", "admin"):
        script = (ROOT / f"frontend/{app_name}/app.js").read_text(encoding="utf-8")
        html = (ROOT / f"frontend/{app_name}/index.html").read_text(encoding="utf-8")
        assert "window.API_BASE_URL" not in script
        assert "__API_BASE__" not in script
        assert 'localStorage.getItem("api_base_url")' not in script
        assert "127.0.0.1:8000" not in script
        assert '../shared/config.js' in html
        assert "SUPPORTAI_CONFIG.API_URL" in script


def test_n5_admin_ticket_dropdown_values_match_ticket_status_enum():
    app_js = (ROOT / "frontend/admin/app.js").read_text(encoding="utf-8")
    block = re.search(r'<select\s+class="case-status-select".*?</select>', app_js, re.DOTALL)
    assert block
    dropdown_values = [value for value in re.findall(r'<option value="([^"]+)"', block.group(0)) if "${" not in value]
    assert set(dropdown_values) == {status.value for status in TicketStatus}
    assert '![' in block.group(0)  # Unknown status remains a selected option.


def test_l4_feedback_cannot_claim_to_remove_persisted_rating():
    script = (ROOT / "frontend/demo-customer/app.js").read_text(encoding="utf-8")
    assert "Feedback removed." not in script
    assert "if (wasSelected) return;" in script


def test_n10_no_obsolete_mobile_menu_button_reference():
    for path in (ROOT / "frontend").rglob("*"):
        if path.is_file():
            assert "mobileMenuBtn" not in path.read_text(encoding="utf-8", errors="ignore")
