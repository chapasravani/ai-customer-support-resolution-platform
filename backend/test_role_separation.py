"""
Role Separation & Dashboard Security Test Suite:
1. Admin token accessing customer-only endpoints is denied (HTTP 403).
2. Customer token accessing admin-only endpoints is denied (HTTP 403).
3. Unauthenticated requests receive HTTP 401.
4. Customer A cannot access Customer B's data (conversations, tickets, orders).
5. Public registration cannot create an admin account (HTTP 400).
6. Frontend admin redirect: admin opening customer dashboard is redirected to /admin/.
7. Frontend customer access: customer opening customer dashboard operates normally.
8. Frontend admin protection: customer opening admin URL cannot access admin dashboard.
9. Existing authorized admin operations continue to work.
10. Existing authorized customer chat, conversation history, and auth continue to work.
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend import auth, db, models
from backend.main import app
from final_customer_support.tools import business_actions

client = TestClient(app)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def test_users():
    """Create isolated test users in database and yield tokens."""
    uid = uuid4().hex[:6]
    admin_email = f"test_admin_{uid}@supportai.com"
    cust_a_email = f"test_cust_a_{uid}@example.com"
    cust_b_email = f"test_cust_b_{uid}@example.com"

    pwd_hash = auth.hash_password("Password123!")

    admin_user = models.create_user(admin_email, pwd_hash, "Test Admin", "admin")
    cust_a_user = models.create_user(cust_a_email, pwd_hash, "Customer A", "customer")
    cust_b_user = models.create_user(cust_b_email, pwd_hash, "Customer B", "customer")

    admin_token = auth.create_access_token(str(admin_user["_id"]), "admin")
    cust_a_token = auth.create_access_token(str(cust_a_user["_id"]), "customer")
    cust_b_token = auth.create_access_token(str(cust_b_user["_id"]), "customer")

    yield {
        "admin": {"user": admin_user, "token": admin_token, "headers": {"Authorization": f"Bearer {admin_token}"}},
        "cust_a": {"user": cust_a_user, "token": cust_a_token, "headers": {"Authorization": f"Bearer {cust_a_token}"}},
        "cust_b": {"user": cust_b_user, "token": cust_b_token, "headers": {"Authorization": f"Bearer {cust_b_token}"}},
    }

    # Cleanup
    database = db.get_db()
    database.users.delete_many({"_id": {"$in": [admin_user["_id"], cust_a_user["_id"], cust_b_user["_id"]]}})
    database.conversations.delete_many({"user_id": {"$in": [str(admin_user["_id"]), str(cust_a_user["_id"]), str(cust_b_user["_id"])]}})
    database.tickets.delete_many({"user_id": {"$in": [str(admin_user["_id"]), str(cust_a_user["_id"]), str(cust_b_user["_id"])]}})


# ---------------------------------------------------------------------------
# 1. Admin token accessing customer-only endpoints is denied (403)
# ---------------------------------------------------------------------------

def test_01_admin_denied_on_customer_chat_endpoints(test_users):
    headers = test_users["admin"]["headers"]

    # POST /chat/message
    resp_msg = client.post("/chat/message", json={"message": "Hello from admin"}, headers=headers)
    assert resp_msg.status_code == 403
    assert "customer access required" in resp_msg.json()["detail"].lower()

    # GET /chat/conversations
    resp_convs = client.get("/chat/conversations", headers=headers)
    assert resp_convs.status_code == 403
    assert "customer access required" in resp_convs.json()["detail"].lower()

    # GET /chat/conversations/{id}
    fake_cid = "60c72b2f9b1d8b2bad000000"
    resp_get = client.get(f"/chat/conversations/{fake_cid}", headers=headers)
    assert resp_get.status_code == 403

    # PATCH /chat/conversations/{id}
    resp_patch = client.patch(f"/chat/conversations/{fake_cid}", json={"title": "Admin Title"}, headers=headers)
    assert resp_patch.status_code == 403

    # DELETE /chat/conversations/{id}
    resp_del = client.delete(f"/chat/conversations/{fake_cid}", headers=headers)
    assert resp_del.status_code == 403

    # POST /chat/feedback
    resp_fb = client.post("/chat/feedback", json={"conversation_id": fake_cid, "rating": 5}, headers=headers)
    assert resp_fb.status_code == 403


# ---------------------------------------------------------------------------
# 2. Customer token accessing admin-only endpoints is denied (403)
# ---------------------------------------------------------------------------

def test_02_customer_denied_on_admin_endpoints(test_users):
    headers = test_users["cust_a"]["headers"]

    # GET /admin/documents
    resp_docs = client.get("/admin/documents", headers=headers)
    assert resp_docs.status_code == 403
    assert "admin access required" in resp_docs.json()["detail"].lower()

    # POST /admin/documents/upload
    resp_upload = client.post(
        "/admin/documents/upload",
        files={"file": ("test.txt", b"Support document content", "text/plain")},
        headers=headers,
    )
    assert resp_upload.status_code == 403
    assert "admin access required" in resp_upload.json()["detail"].lower()

    # DELETE /admin/documents/{id}
    fake_doc_id = "60c72b2f9b1d8b2bad000001"
    resp_del = client.delete(f"/admin/documents/{fake_doc_id}", headers=headers)
    assert resp_del.status_code == 403
    assert "admin access required" in resp_del.json()["detail"].lower()

    # PATCH /tickets/{ticket_id} (admin only)
    resp_ticket = client.patch(
        "/tickets/CASE-12345678",
        json={"status": "resolved", "resolution_summary": "Customer trying to resolve"},
        headers=headers,
    )
    assert resp_ticket.status_code == 403
    assert "admin access required" in resp_ticket.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 3. Unauthenticated requests receive HTTP 401
# ---------------------------------------------------------------------------

def test_03_unauthenticated_requests_receive_401():
    endpoints = [
        ("POST", "/chat/message", {"json": {"message": "unauth"}}),
        ("GET", "/chat/conversations", {}),
        ("GET", "/auth/me", {}),
        ("GET", "/admin/documents", {}),
        ("GET", "/tickets", {}),
        ("PATCH", "/tickets/CASE-12345678", {"json": {"status": "in_progress"}}),
    ]

    for method, path, kwargs in endpoints:
        if method == "POST":
            resp = client.post(path, **kwargs)
        elif method == "GET":
            resp = client.get(path, **kwargs)
        elif method == "PATCH":
            resp = client.patch(path, **kwargs)
        assert resp.status_code == 401, f"Expected 401 for unauthenticated {method} {path}, got {resp.status_code}"


# ---------------------------------------------------------------------------
# 4. Customer A cannot access Customer B's data
# ---------------------------------------------------------------------------

def test_04_cross_customer_data_isolation(test_users):
    cust_a = test_users["cust_a"]
    cust_b = test_users["cust_b"]

    # Customer A creates a conversation
    conv_a = models.create_conversation(str(cust_a["user"]["_id"]))
    models.rename_conversation(str(conv_a["_id"]), "Customer A Secret")
    conv_a_id = str(conv_a["_id"])

    # Customer B attempts to read Customer A's conversation
    resp_get = client.get(f"/chat/conversations/{conv_a_id}", headers=cust_b["headers"])
    assert resp_get.status_code == 404

    # Customer B attempts to rename Customer A's conversation
    resp_rename = client.patch(f"/chat/conversations/{conv_a_id}", json={"title": "Hacked"}, headers=cust_b["headers"])
    assert resp_rename.status_code == 404

    # Customer B attempts to delete Customer A's conversation
    resp_delete = client.delete(f"/chat/conversations/{conv_a_id}", headers=cust_b["headers"])
    assert resp_delete.status_code == 404

    # Customer A creates a ticket
    ticket_id = f"CASE-{uuid4().hex[:8].upper()}"
    models.create_ticket(ticket_id=ticket_id, user_id=str(cust_a["user"]["_id"]), issue="Screen broken", conversation_id=conv_a_id)

    # Customer B attempts to view Customer A's ticket
    resp_t_b = client.get(f"/tickets/{ticket_id}", headers=cust_b["headers"])
    assert resp_t_b.status_code == 403
    assert "do not have access" in resp_t_b.json()["detail"].lower()

    # Customer A can view their own ticket
    resp_t_a = client.get(f"/tickets/{ticket_id}", headers=cust_a["headers"])
    assert resp_t_a.status_code == 200
    assert resp_t_a.json()["ticket_id"] == ticket_id

    # Cross-customer order action blocked
    res_action = business_actions.create_refund_request(order_id="ORD123", reason="testing", customer_id="C102")
    assert res_action.get("status") == "rejected"
    assert "ownership verification failed" in res_action.get("reason", "").lower()


# ---------------------------------------------------------------------------
# 5. Public registration cannot create an admin account
# ---------------------------------------------------------------------------

def test_05_public_registration_cannot_create_admin():
    # Explicit role="admin" rejected
    resp_admin = client.post(
        "/auth/register",
        json={"email": "attacker@supportai.com", "password": "Password123!", "name": "Attacker", "role": "admin"},
    )
    assert resp_admin.status_code == 400
    assert "prohibited" in resp_admin.json()["detail"].lower()

    # Role manipulation with casing/whitespace rejected
    resp_admin_sneaky = client.post(
        "/auth/register",
        json={"email": "attacker2@supportai.com", "password": "Password123!", "name": "Attacker", "role": "  Admin "},
    )
    assert resp_admin_sneaky.status_code == 400

    # Clean registration forced to customer
    new_email = f"clean_cust_{uuid4().hex[:6]}@example.com"
    resp_clean = client.post(
        "/auth/register",
        json={"email": new_email, "password": "Password123!", "name": "Clean Customer"},
    )
    assert resp_clean.status_code == 200
    assert resp_clean.json()["role"] == "customer"
    db.get_db().users.delete_one({"email": new_email})


# ---------------------------------------------------------------------------
# 6. Frontend admin redirect: admin opening customer dashboard redirected to /admin/
# ---------------------------------------------------------------------------

def test_06_frontend_admin_redirect_logic():
    cust_js = (PROJECT_ROOT / "frontend" / "customer" / "app.js").read_text(encoding="utf-8")

    # Verify admin redirection in initializeAuthenticatedApp
    assert 'user.role === "admin"' in cust_js
    assert 'window.location.replace("../admin/")' in cust_js

    # Verify admin check in handleLogin
    assert 'data.role === "admin"' in cust_js
    assert 'localStorage.setItem("admin_token"' in cust_js

    # Verify customer UI is not rendered prematurely before validation
    assert 'updateUserUI()' not in cust_js.split('document.addEventListener("DOMContentLoaded"')[1].split('initializeAuthenticatedApp()')[0]


# ---------------------------------------------------------------------------
# 7. Frontend customer access: customer opening customer dashboard operates normally
# ---------------------------------------------------------------------------

def test_07_frontend_customer_access_logic():
    cust_js = (PROJECT_ROOT / "frontend" / "customer" / "app.js").read_text(encoding="utf-8")

    # Verify customer role activates customer state and loads data
    assert 'user.role === "customer"' in cust_js
    assert 'updateUserUI()' in cust_js
    assert 'hideEntryScreen()' in cust_js
    assert 'loadConversations()' in cust_js


# ---------------------------------------------------------------------------
# 8. Frontend admin protection: customer opening admin URL cannot access admin dashboard
# ---------------------------------------------------------------------------

def test_08_frontend_admin_protection_logic():
    admin_html = (PROJECT_ROOT / "frontend" / "admin" / "index.html").read_text(encoding="utf-8")
    admin_js = (PROJECT_ROOT / "frontend" / "admin" / "app.js").read_text(encoding="utf-8")

    # Admin dashboard section is hidden by default in markup
    assert 'class="dashboard hidden"' in admin_html

    # Admin JS rejects non-admin users and redirects customers back to customer dashboard
    assert 'state.user.role !== "admin"' in admin_js
    assert 'window.location.replace("../customer/")' in admin_js
    assert 'data.role && data.role !== "admin"' in admin_js


# ---------------------------------------------------------------------------
# 9. Existing authorized admin operations continue to work
# ---------------------------------------------------------------------------

def test_09_authorized_admin_operations_work(test_users):
    admin = test_users["admin"]

    # /auth/me returns admin role
    resp_me = client.get("/auth/me", headers=admin["headers"])
    assert resp_me.status_code == 200
    assert resp_me.json()["role"] == "admin"

    # GET /admin/documents succeeds
    resp_docs = client.get("/admin/documents", headers=admin["headers"])
    assert resp_docs.status_code == 200
    assert isinstance(resp_docs.json(), list)

    # GET /tickets succeeds for admin (sees all tickets)
    resp_tickets = client.get("/tickets", headers=admin["headers"])
    assert resp_tickets.status_code == 200
    assert isinstance(resp_tickets.json(), list)

    # Admin can update ticket status
    t_id = f"CASE-{uuid4().hex[:8].upper()}"
    models.create_ticket(ticket_id=t_id, user_id=str(admin["user"]["_id"]), issue="Admin test case")
    resp_patch = client.patch(f"/tickets/{t_id}", json={"status": "in_progress", "resolution_summary": "Investigating"}, headers=admin["headers"])
    assert resp_patch.status_code == 200
    assert resp_patch.json()["status"] == "in_progress"


# ---------------------------------------------------------------------------
# 10. Existing authorized customer chat and history operations continue to work
# ---------------------------------------------------------------------------

def test_10_authorized_customer_chat_operations_work(test_users):
    cust_a = test_users["cust_a"]

    # /auth/me returns customer role
    resp_me = client.get("/auth/me", headers=cust_a["headers"])
    assert resp_me.status_code == 200
    assert resp_me.json()["role"] == "customer"

    # GET /chat/conversations succeeds for customer
    resp_convs = client.get("/chat/conversations", headers=cust_a["headers"])
    assert resp_convs.status_code == 200
    assert isinstance(resp_convs.json(), list)

    # Customer can send a message with mocked ADK workflow (no external LLM needed)
    with patch("backend.routes.chat.run_support_workflow", new_callable=AsyncMock) as mock_workflow:
        mock_workflow.return_value = {
            "response": "Hello! I am your AI assistant. How can I help you today?",
            "success": True,
            "escalation": {},
            "order_id": "",
            "issue_type": "general",
        }

        resp_msg = client.post("/chat/message", json={"message": "Hi, I have a question"}, headers=cust_a["headers"])
        assert resp_msg.status_code == 200
        data = resp_msg.json()
        assert "conversation_id" in data
        assert "Hello!" in data["response"]

        # Customer can retrieve their active conversation
        cid = data["conversation_id"]
        resp_c = client.get(f"/chat/conversations/{cid}", headers=cust_a["headers"])
        assert resp_c.status_code == 200
        assert len(resp_c.json()["messages"]) >= 2
