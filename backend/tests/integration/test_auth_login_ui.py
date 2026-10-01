"""
Comprehensive test suite for:
- Authentication & persistence (Customer registration/login, Admin login, Role checks, 503 error handling, Storage persistence)
- Password visibility icon positioning & controls across customer and admin
- Admin close icon positioning & navigation
- Responsive customer conversation sidebar toggle & drawer
"""

import os
import subprocess
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from backend.app.core import security
from backend.app.infrastructure import db
from backend.app.domains import models
from backend.app.main import app

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module", autouse=True)
def setup_isolated_test_storage(tmp_path_factory):
    """
    Ensure all tests run against an isolated temporary database file,
    preserving committed and existing data in data/runtime/db_store.json.
    """
    temp_dir = tmp_path_factory.mktemp("test_auth_data")
    test_data_file = temp_dir / "db_store_test.json"

    old_env = os.environ.get("SUPPORTAI_DATA_FILE")
    os.environ["SUPPORTAI_DATA_FILE"] = str(test_data_file)
    db.set_local_mode()

    # Seed isolated known accounts for testing
    models.create_user(
        email="admin@supportai.com",
        hashed_password=security.hash_password("AdminPassword123!"),
        name="System Administrator",
        role="admin"
    )
    models.create_user(
        email="cust_matrix@supportai.com",
        hashed_password=security.hash_password("Password123!"),
        name="Matrix Customer",
        role="customer"
    )

    yield

    if old_env is not None:
        os.environ["SUPPORTAI_DATA_FILE"] = old_env
    else:
        os.environ.pop("SUPPORTAI_DATA_FILE", None)


# ============================================================
# 1. AUTHENTICATION & STORAGE INTEGRITY
# ============================================================

def test_1_customer_registration_and_immediate_login():
    """Verify customer registration creates an account and returns valid JWT."""
    client = TestClient(app)
    reg_res = client.post("/auth/register", json={
        "name": "Jane Doe",
        "email": "jane.doe@example.com",
        "password": "JanePassword123!",
        "role": "customer"
    })
    assert reg_res.status_code == 202, reg_res.text
    assert reg_res.json() == {"detail": "If this email can be registered, you can now log in."}

    # Verify user can immediately log in with registered credentials
    login_res = client.post("/auth/login", json={
        "email": "jane.doe@example.com",
        "password": "JanePassword123!"
    })
    assert login_res.status_code == 200
    login_data = login_res.json()
    assert "access_token" in login_data
    assert login_data["role"] == "customer"


def test_2_customer_email_case_insensitivity():
    """Verify that uppercase/mixed-case email registration and login work seamlessly."""
    client = TestClient(app)
    # Login with uppercase version of existing account
    res = client.post("/auth/login", json={
        "email": "JANE.DOE@EXAMPLE.COM",
        "password": "JanePassword123!"
    })
    assert res.status_code == 200
    assert res.json()["role"] == "customer"


def test_3_login_rejects_incorrect_password():
    """Verify incorrect password returns HTTP 401."""
    client = TestClient(app)
    res = client.post("/auth/login", json={
        "email": "jane.doe@example.com",
        "password": "WrongPassword999!"
    })
    assert res.status_code == 401
    assert res.json()["detail"] == "Incorrect email or password."


def test_4_duplicate_registration_uses_generic_response():
    """Existing and new addresses receive the same registration response."""
    client = TestClient(app)
    res = client.post("/auth/register", json={
        "name": "Duplicate Jane",
        "email": "jane.doe@example.com",
        "password": "AnotherPassword123!"
    })
    assert res.status_code == 202
    assert res.json() == {"detail": "If this email can be registered, you can now log in."}


def test_5_public_registration_cannot_create_admin():
    """Verify public registration with role='admin' is strictly rejected."""
    client = TestClient(app)
    res = client.post("/auth/register", json={
        "name": "Hacker",
        "email": "hacker@example.com",
        "password": "HackerPassword123!",
        "role": "admin"
    })
    assert res.status_code == 400
    assert "prohibited" in res.json()["detail"].lower()


def test_6_admin_login_and_role_validation():
    """Verify admin login succeeds and provides admin role."""
    client = TestClient(app)
    res = client.post("/auth/login", json={
        "email": "admin@supportai.com",
        "password": "AdminPassword123!"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["role"] == "admin"

    # Verify /auth/me returns admin
    me_res = client.get("/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"})
    assert me_res.status_code == 200
    assert me_res.json()["role"] == "admin"


def test_7_customer_cannot_access_admin_routes():
    """Verify admin-only endpoints reject customer tokens with HTTP 403."""
    client = TestClient(app)
    # Obtain customer token
    cust_res = client.post("/auth/login", json={
        "email": "cust_matrix@supportai.com",
        "password": "Password123!"
    })
    cust_token = cust_res.json()["access_token"]

    # Customer attempts to access admin document list
    res = client.get("/admin/documents", headers={"Authorization": f"Bearer {cust_token}"})
    assert res.status_code == 403


def test_8_database_failure_returns_503():
    """Verify that backend exceptions during lookup return 503 instead of masking as 401."""
    client = TestClient(app)
    with patch("backend.app.domains.models.get_user_by_email", side_effect=RuntimeError("DB dropped")):
        res = client.post("/auth/login", json={
            "email": "admin@supportai.com",
            "password": "AdminPassword123!"
        })
        assert res.status_code == 503
        assert "Database service is temporarily unavailable" in res.json()["detail"]


def test_9_account_persistence_across_backend_reloads():
    """Verify that accounts persist across mock client re-instantiations."""
    # Ensure current user exists in disk store
    user_before = models.get_user_by_email("jane.doe@example.com")
    assert user_before is not None

    # Simulate backend restart by resetting client instance
    db._client = None
    db.set_local_mode()

    user_after = models.get_user_by_email("jane.doe@example.com")
    assert user_after is not None
    assert user_after["email"] == "jane.doe@example.com"
    assert security.verify_password("JanePassword123!", user_after["hashed_password"])


# ============================================================
# 2. FRONTEND STRUCTURE & CODE QUALITY
# ============================================================

def test_10_js_syntax_cleanliness():
    """Verify both admin and customer JS files parse cleanly with zero syntax errors."""
    for js_rel in ["frontend/admin/app.js", "frontend/demo-customer/app.js"]:
        p = PROJECT_ROOT / js_rel
        run_res = subprocess.run(["node", "-c", str(p)], capture_output=True, text=True)
        assert run_res.returncode == 0, f"Syntax error in {js_rel}: {run_res.stderr}"


def test_11_password_visibility_icons_inside_input_right_aligned():
    """Verify password wrappers, input padding, and right-aligned absolute buttons."""
    admin_css = (PROJECT_ROOT / "frontend" / "admin" / "style.css").read_text(encoding="utf-8")
    customer_css = (PROJECT_ROOT / "frontend" / "demo-customer" / "style.css").read_text(encoding="utf-8")

    for css in [admin_css, customer_css]:
        assert ".password-input-wrapper" in css
        assert "padding-right: 44px" in css
        assert ".password-toggle-btn" in css
        assert "right: 10px" in css
        assert "position: absolute" in css


def test_12_password_toggle_buttons_and_accessibility():
    """Verify password inputs have dedicated toggle buttons with accessible labels."""
    admin_html = (PROJECT_ROOT / "frontend" / "admin" / "index.html").read_text(encoding="utf-8")
    customer_html = (PROJECT_ROOT / "frontend" / "demo-customer" / "index.html").read_text(encoding="utf-8")

    assert 'id="adminPasswordToggle"' in admin_html
    assert 'aria-controls="password"' in admin_html

    assert 'id="loginPasswordToggle"' in customer_html
    assert 'aria-controls="loginPassword"' in customer_html

    assert 'id="registerPasswordToggle"' in customer_html
    assert 'aria-controls="registerPassword"' in customer_html


def test_13_admin_card_close_button_top_right():
    """Verify the admin login card close button is in top-right corner with proper navigation."""
    admin_html = (PROJECT_ROOT / "frontend" / "admin" / "index.html").read_text(encoding="utf-8")
    admin_css = (PROJECT_ROOT / "frontend" / "admin" / "style.css").read_text(encoding="utf-8")
    admin_js = (PROJECT_ROOT / "frontend" / "admin" / "app.js").read_text(encoding="utf-8")

    assert 'id="closeAuthModal"' in admin_html
    assert '.auth-card .modal-close' in admin_css
    assert "top: 16px" in admin_css
    assert "right: 16px" in admin_css
    assert "border-radius: 50%" in admin_css
    assert "closeAuthModal" in admin_js
    assert "../demo-customer/" in admin_js


def test_14_customer_sidebar_toggle_and_responsive_drawer():
    """Verify customer sidebar has toggle button, backdrop, and CSS state classes."""
    cust_html = (PROJECT_ROOT / "frontend" / "demo-customer" / "index.html").read_text(encoding="utf-8")
    cust_css = (PROJECT_ROOT / "frontend" / "demo-customer" / "style.css").read_text(encoding="utf-8")
    cust_js = (PROJECT_ROOT / "frontend" / "demo-customer" / "app.js").read_text(encoding="utf-8")

    assert 'id="sidebarToggleBtn"' in cust_html
    assert 'id="sidebarBackdrop"' in cust_html
    assert ".sidebar.collapsed" in cust_css
    assert ".sidebar.open" in cust_css
    assert ".sidebar-backdrop" in cust_css
    assert "toggleSidebar" in cust_js
    assert "closeMobileSidebar" in cust_js
    assert "updateSidebarUI" in cust_js
