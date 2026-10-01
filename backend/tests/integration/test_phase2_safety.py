"""
Phase 2 Safety Test Suite:
- C6: Request deduplication and safe retries
- H1: Single open ticket contract per conversation
- N3: Trusted backend ticket ID generation (no LLM ID authority)
- N12: Admin pending human approval workflows (list, approve, reject with audit)
"""

import json
from unittest.mock import patch
from fastapi.testclient import TestClient
import pytest

from backend.app.core import security
from backend.app.infrastructure import db
from backend.app.domains import models
from backend.app.main import app
from backend.app.workflows.support_agent.tools import business_actions

client = TestClient(app)


@pytest.fixture(autouse=True)
def cleanup_users_and_tickets():
    test_emails = ["phase2_cust@example.com", "phase2_admin@example.com"]
    for email in test_emails:
        db.get_db().users.delete_one({"email": email})
    yield
    for email in test_emails:
        db.get_db().users.delete_one({"email": email})


def test_n12_admin_actions_endpoints(tmp_path, monkeypatch):
    """N12: Admin-only list and approve/reject operations for pending human approvals."""
    # Setup temporary actions.json
    temp_actions = {
        "APR-20261001-001": {
            "action": "refund",
            "order_id": "ORD123",
            "status": "pending_human_approval",
            "reference": "APR-20261001-001",
            "reason": "high value refund",
            "amount": 1299,
        },
        "REF-20261001-002": {
            "action": "refund",
            "order_id": "ORD124",
            "status": "created",
            "reference": "REF-20261001-002",
            "reason": "damaged item",
            "amount": 149,
        },
    }
    (tmp_path / "actions.json").write_text(json.dumps(temp_actions), encoding="utf-8")
    monkeypatch.setattr(business_actions, "DATA", tmp_path)

    # Create admin and customer tokens
    admin_user = models.create_user("phase2_admin@example.com", "Password123!", "Admin User", role="admin")
    admin_token = security.create_access_token(str(admin_user["_id"]), role="admin")

    cust_user = models.create_user("phase2_cust@example.com", "Password123!", "Customer User", role="customer")
    cust_token = security.create_access_token(str(cust_user["_id"]), role="customer")

    # 1. Customer cannot access /admin/actions (403)
    resp = client.get("/admin/actions", headers={"Authorization": f"Bearer {cust_token}"})
    assert resp.status_code == 403

    # 2. Admin can list all actions
    resp = client.get("/admin/actions", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2

    # 3. Admin can filter by status=pending_human_approval
    resp_pending = client.get("/admin/actions?status=pending_human_approval", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp_pending.status_code == 200
    pending_items = resp_pending.json()
    assert len(pending_items) == 1
    assert pending_items[0]["reference"] == "APR-20261001-001"

    # 4. Reject modifying an action that is not pending approval (REF-20261001-002 has status created)
    resp_inv = client.patch(
        "/admin/actions/REF-20261001-002",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"status": "approved", "reason": "invalid state transition"},
    )
    assert resp_inv.status_code == 400
    assert "not pending approval" in resp_inv.json()["detail"].lower()

    # 5. Non-existent action returns 404
    resp_404 = client.patch(
        "/admin/actions/NON-EXISTENT",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"status": "approved", "reason": "does not exist"},
    )
    assert resp_404.status_code == 404

    # 6. Customer cannot approve or reject actions (403)
    resp_cust_patch = client.patch(
        "/admin/actions/APR-20261001-001",
        headers={"Authorization": f"Bearer {cust_token}"},
        json={"status": "approved", "reason": "trying unauthorized"},
    )
    assert resp_cust_patch.status_code == 403

    # 7. Admin approves APR-20261001-001
    resp_app = client.patch(
        "/admin/actions/APR-20261001-001",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"status": "approved", "reason": "Customer is VIP, approved refund."},
    )
    assert resp_app.status_code == 200
    app_data = resp_app.json()
    assert app_data["status"] == "approved"
    assert app_data["reviewer"] == "phase2_admin@example.com"
    assert app_data["review_reason"] == "Customer is VIP, approved refund."
    assert "reviewed_at" in app_data
    assert "resolution_reference" in app_data
    assert app_data["resolution_reference"].startswith("REF-")

    # 8. Action is no longer in pending_human_approval list
    resp_pending2 = client.get("/admin/actions?status=pending_human_approval", headers={"Authorization": f"Bearer {admin_token}"})
    assert len(resp_pending2.json()) == 0


def test_h1_and_n3_single_open_ticket_and_trusted_id():
    """H1 & N3: Backend generates CASE- id and prevents duplicate open tickets per conversation."""
    cust_user = models.create_user("phase2_cust@example.com", "Password123!", "Customer User", role="customer")
    cust_token = security.create_access_token(str(cust_user["_id"]), role="customer")

    convo = models.create_conversation(str(cust_user["_id"]))
    convo_id = str(convo["_id"])

    # First turn requiring escalation:
    mock_workflow_turn1 = {
        "response": "I am escalating your issue to a specialist.",
        "success": True,
        "escalation": {
            "should_escalate": True,
            "reason": "Defective item needs supervisor approval",
            "case_id": "MALICIOUS-CASE-1234",  # Model-proposed untrusted case ID
        },
        "order_id": "ORD123",
        "issue_type": "damaged",
    }

    with patch("backend.app.api.routes.chat.run_support_workflow", return_value=mock_workflow_turn1):
        resp1 = client.post(
            "/chat/message",
            headers={"Authorization": f"Bearer {cust_token}"},
            json={"message": "My item is defective, please escalate.", "conversation_id": convo_id},
        )
        assert resp1.status_code == 200

    # N3: Authoritative backend-generated ticket ID (NOT MALICIOUS-CASE-1234)
    ticket1 = models.get_ticket_for_conversation(convo_id)
    assert ticket1 is not None
    assert ticket1["ticket_id"].startswith("CASE-")
    assert ticket1["ticket_id"] != "MALICIOUS-CASE-1234"
    assert ticket1["source_reference"] == ""
    assert ticket1["ticket_id"] in resp1.json()["response"]
    assert ticket1["status"] == "open"
    orig_ticket_id = ticket1["ticket_id"]

    # Second turn in the SAME conversation also requiring escalation:
    mock_workflow_turn2 = {
        "response": "Still escalating to specialist.",
        "success": True,
        "escalation": {
            "should_escalate": True,
            "reason": "Updated description of defective item",
            "case_id": "ANOTHER-CASE-ID",
        },
        "order_id": "ORD123",
        "issue_type": "damaged",
    }

    with patch("backend.app.api.routes.chat.run_support_workflow", return_value=mock_workflow_turn2):
        resp2 = client.post(
            "/chat/message",
            headers={"Authorization": f"Bearer {cust_token}"},
            json={"message": "Any updates on my escalated issue?", "conversation_id": convo_id},
        )
        assert resp2.status_code == 200

    # H1: Verify only ONE ticket exists for this conversation and the existing ticket was reused/updated
    all_convo_tickets = list(db.get_db().tickets.find({"$or": [{"conversation_id": models._oid(convo_id)}, {"conversation_id": convo_id}]}))
    assert len(all_convo_tickets) == 1
    assert all_convo_tickets[0]["ticket_id"] == orig_ticket_id
    assert all_convo_tickets[0]["issue"] == "Updated description of defective item"


def test_c6_request_id_deduplication():
    """C6: Retrying with identical request_id does not re-run workflow or generate duplicate side effects."""
    cust_user = models.create_user("phase2_cust@example.com", "Password123!", "Customer User", role="customer")
    cust_token = security.create_access_token(str(cust_user["_id"]), role="customer")

    convo = models.create_conversation(str(cust_user["_id"]))
    convo_id = str(convo["_id"])

    call_count = 0

    async def counting_workflow(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return {
            "response": f"Response count {call_count}",
            "success": True,
            "escalation": {},
            "order_id": "",
            "issue_type": "",
        }

    with patch("backend.app.api.routes.chat.run_support_workflow", side_effect=counting_workflow):
        # First send with request_id="req-abc-123"
        resp1 = client.post(
            "/chat/message",
            headers={"Authorization": f"Bearer {cust_token}"},
            json={"message": "Hello support", "conversation_id": convo_id, "request_id": "req-abc-123"},
        )
        assert resp1.status_code == 200
        assert call_count == 1
        assert resp1.json()["response"] == "Response count 1"

        # Retry with identical request_id="req-abc-123"
        resp2 = client.post(
            "/chat/message",
            headers={"Authorization": f"Bearer {cust_token}"},
            json={"message": "Hello support", "conversation_id": convo_id, "request_id": "req-abc-123"},
        )
        assert resp2.status_code == 200
        # Workflow was NOT rerun!
        assert call_count == 1
        assert resp2.json()["deduplicated"] is True
        assert resp2.json()["response"] == "Response count 1"
