"""
Phase 7 verification test suite — Low Priority & Maintainability (L1–L6).

How to run:
    py -3.12 -m backend.test_phase7_low
or:
    pytest backend/test_phase7_low.py

What it tests:
    1. L1 — Documentation consistency across READMEs and .env.examples.
    2. L2 — Dead code removal, carrier agent preservation, and case ID collision resistance.
    3. L3 — Ticket update correctness (no-op status updates succeed and do not return 404).
    4. L4 — Customer feedback persistence and validation.
    5. L5 — API configuration flexibility across customer and admin frontend scripts.
    6. L6 — Conversation list pagination and message exclusion in summaries.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend import db, models
from backend.api_schemas import FeedbackRequest, TicketStatus, TicketStatusUpdate
from backend.routes import chat, tickets


# ============================================================================
# L1 — Documentation consistency
# ============================================================================

def test_l1_documentation_consistency():
    print("Testing L1 — Documentation consistency...")
    root_readme = Path("README.md").read_text(encoding="utf-8")
    adk_readme = Path("final_customer_support/README.md").read_text(encoding="utf-8")
    env_example = Path("backend/.env.example").read_text(encoding="utf-8")

    # Verify all phase suites are documented
    for phase_num in range(1, 8):
        assert f"test_phase{phase_num}" in root_readme or f"test_phase{phase_num}_" in root_readme

    # Verify no hardcoded secrets exist in example files
    assert "your_gemini_api_key_here" in env_example
    assert "your_jwt_secret_min_32_chars_here" in env_example

    # Verify CORS_ORIGINS is documented
    assert "CORS_ORIGINS" in root_readme
    assert "CORS_ORIGINS" in env_example
    print("  [OK] Documentation across READMEs and .env.example is consistent and safe.")


# ============================================================================
# L2 — Dead code and maintainability
# ============================================================================

def test_l2_dead_code_and_case_id_uniqueness():
    print("Testing L2 — Dead code cleanups, carrier agent, and case ID uniqueness...")
    # Verify carrier agent is preserved in agent.py
    agent_code = Path("final_customer_support/agent.py").read_text(encoding="utf-8")
    assert "carrier_investigation_agent" in agent_code
    assert "start_carrier_investigation" in agent_code

    # Verify case ID collision resistance with UUID suffixes
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        cases_file = tmp_path / "support_cases.json"
        cases_file.write_text("{}", encoding="utf-8")

        from final_customer_support import mcp_server, openapi_server
        with patch.object(mcp_server, "DATA_DIR", tmp_path):
            case1 = mcp_server.create_support_case_mcp("CUST-1", "ORD-1", "Issue 1")
            case2 = mcp_server.create_support_case_mcp("CUST-2", "ORD-2", "Issue 2")
            assert case1["case_id"] != case2["case_id"], "MCP case IDs must be unique"

        with patch.object(openapi_server, "DATA", tmp_path):
            case3 = openapi_server.support_case({"customer_id": "CUST-3", "order_id": "ORD-3", "issue": "Issue 3"})
            case4 = openapi_server.support_case({"customer_id": "CUST-4", "order_id": "ORD-4", "issue": "Issue 4"})
            assert case3["case_id"] != case4["case_id"], "OpenAPI case IDs must be unique"

    # Verify unused imports removed from db.py
    db_code = Path("backend/db.py").read_text(encoding="utf-8")
    assert "from typing import Optional" not in db_code
    assert "from pymongo.database import Database" not in db_code
    print("  [OK] Carrier workflow preserved, case IDs collision-resistant, dead code removed.")


# ============================================================================
# L3 — Ticket update correctness (no-op updates)
# ============================================================================

def test_l3_ticket_update_correctness():
    print("Testing L3 — Ticket update correctness (no-op updates succeed)...")
    uid = uuid4().hex[:8]
    user = models.create_user(f"l3.test_{uid}@example.com", "hash", "L3 Test", "customer")
    user_id = str(user["_id"])
    ticket_id = f"TICKET-L3-{uid}"
    ticket = models.create_ticket(
        ticket_id=ticket_id,
        user_id=user_id,
        issue="Test issue",
        status="in_progress",
    )

    try:
        # 1. Update to a new status
        success = models.update_ticket_status(ticket_id, "resolved", "Resolved issue")
        assert success is True
        updated = models.get_ticket(ticket_id)
        assert updated["status"] == "resolved"

        # 2. No-op update with identical status & resolution
        # In MongoDB, modified_count is 0, but matched_count is 1.
        noop_success = models.update_ticket_status(ticket_id, "resolved", "Resolved issue")
        assert noop_success is True, "No-op update must succeed when the ticket exists"

        # 3. Via API route: should succeed with status 200, not 404
        admin_user = {"_id": "admin_test", "role": "admin"}
        payload = TicketStatusUpdate(status=TicketStatus.RESOLVED, resolution_summary="Resolved issue")
        res = tickets.update_ticket(ticket_id, payload, admin=admin_user)
        assert res["status"] == "resolved"

        # 4. Non-existent ticket must fail with 404
        with pytest.raises(HTTPException) as exc_info:
            tickets.update_ticket("NON-EXISTENT-TICKET", payload, admin=admin_user)
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Ticket not found."
        print("  [OK] No-op ticket status updates succeed without false 404s.")
    finally:
        db.get_db().users.delete_one({"_id": user["_id"]})
        db.get_db().tickets.delete_one({"ticket_id": ticket_id})


# ============================================================================
# L4 — Customer feedback persistence
# ============================================================================

def test_l4_customer_feedback():
    print("Testing L4 — Customer feedback persistence...")
    uid = uuid4().hex[:8]
    user = models.create_user(f"l4.test_{uid}@example.com", "hash", "L4 Test", "customer")
    user_id = str(user["_id"])
    convo = models.create_conversation(user_id)
    convo_id = str(convo["_id"])

    try:
        # 1. Save valid feedback
        success = models.save_feedback(convo_id, user_id, "like", message_index=0)
        assert success is True

        # Verify persisted in DB
        updated_convo = models.get_conversation(convo_id)
        assert "feedback" in updated_convo
        assert len(updated_convo["feedback"]) == 1
        assert updated_convo["feedback"][0]["rating"] == "like"

        # 2. Test via endpoint
        endpoint_res = chat.submit_feedback(
            FeedbackRequest(conversation_id=convo_id, rating="dislike"),
            user=user,
        )
        assert endpoint_res["status"] == "success"

        updated_convo2 = models.get_conversation(convo_id)
        assert len(updated_convo2["feedback"]) == 2
        assert updated_convo2["feedback"][1]["rating"] == "dislike"

        # 3. Validation rejection of invalid rating
        with pytest.raises(ValidationError):
            FeedbackRequest(conversation_id=convo_id, rating="neutral")

        # 4. Ownership protection (other user cannot submit feedback)
        other_user = {"_id": "other_user_id"}
        with pytest.raises(HTTPException) as exc:
            chat.submit_feedback(
                FeedbackRequest(conversation_id=convo_id, rating="like"),
                user=other_user,
            )
        assert exc.value.status_code == 404
        print("  [OK] Customer feedback persisted to MongoDB with validation and ownership enforcement.")
    finally:
        db.get_db().users.delete_one({"_id": user["_id"]})
        db.get_db().conversations.delete_one({"_id": convo["_id"]})


# ============================================================================
# L5 — API configuration
# ============================================================================

def test_l5_api_configuration():
    print("Testing L5 — Configurable frontend API base URLs...")
    customer_js = Path("frontend/customer/app.js").read_text(encoding="utf-8")
    admin_js = Path("frontend/admin/app.js").read_text(encoding="utf-8")

    # Check customer app.js
    assert "window.API_BASE_URL" in customer_js
    assert "localStorage.getItem(\"api_base_url\")" in customer_js
    assert "\"http://127.0.0.1:8000\"" in customer_js

    # Check admin app.js
    assert "window.API_BASE_URL" in admin_js
    assert "localStorage.getItem(\"api_base_url\")" in admin_js
    assert "\"http://127.0.0.1:8000\"" in admin_js
    print("  [OK] Both frontends support dynamic API base URLs with safe defaults.")


# ============================================================================
# L6 — Pagination and conversation loading
# ============================================================================

def test_l6_pagination_and_conversation_loading():
    print("Testing L6 — Conversation pagination and message exclusion...")
    uid = uuid4().hex[:8]
    user = models.create_user(f"l6.test_{uid}@example.com", "hash", "L6 Test", "customer")
    user_id = str(user["_id"])

    # Create 5 conversations with messages
    created_ids = []
    try:
        for i in range(5):
            c = models.create_conversation(user_id)
            cid = str(c["_id"])
            created_ids.append(cid)
            models.add_message(cid, "user", f"Question {i}")
            models.add_message(cid, "assistant", f"Answer {i}")

        # 1. list_conversations_for_user with include_messages=False excludes 'messages' field
        summary_list = models.list_conversations_for_user(user_id, limit=10, include_messages=False)
        assert len(summary_list) == 5
        for item in summary_list:
            assert "messages" not in item, "Message bodies should not be loaded in list summaries"
            assert item.get("message_count") == 2, "Message count must be maintained"

        # 2. Pagination limit and skip
        page1 = models.list_conversations_for_user(user_id, limit=2, skip=0, include_messages=False)
        assert len(page1) == 2

        page2 = models.list_conversations_for_user(user_id, limit=2, skip=2, include_messages=False)
        assert len(page2) == 2
        assert page1[0]["_id"] != page2[0]["_id"], "Pages must return distinct conversation items"

        # 3. GET /chat/conversations endpoint supports limit & skip
        api_list = chat.list_conversations(limit=3, skip=0, user=user)
        assert len(api_list) == 3
        for c_info in api_list:
            assert "messages" not in c_info
            assert c_info["message_count"] == 2
        print("  [OK] Pagination, message exclusion, and message count tracking verified.")
    finally:
        db.get_db().users.delete_one({"_id": user["_id"]})
        for cid in created_ids:
            oid = models._oid(cid)
            if oid:
                db.get_db().conversations.delete_one({"_id": oid})


# ============================================================================
# Run all tests directly
# ============================================================================

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("RUNNING PHASE 7 VERIFICATION TEST SUITE (L1–L6)")
    print("=" * 60)
    test_l1_documentation_consistency()
    test_l2_dead_code_and_case_id_uniqueness()
    test_l3_ticket_update_correctness()
    test_l4_customer_feedback()
    test_l5_api_configuration()
    test_l6_pagination_and_conversation_loading()
    print("=" * 60)
    print("ALL PHASE 7 (L1–L6) TESTS PASSED SUCCESSFULLY!")
    print("=" * 60 + "\n")
