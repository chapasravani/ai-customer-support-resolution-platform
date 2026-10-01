"""
Phase 3 Critical Security Test Suite:
- C1: Admin registration restriction (public /auth/register cannot create admins)
- C2: Customer/order ownership verification (customers cannot access/act on others' orders)
- C7: JWT secret security validation (fail clearly on missing/insecure production secret)
"""

import os
from types import SimpleNamespace
from fastapi.testclient import TestClient

from backend.app.core import security
from backend.app.infrastructure import db
from backend.app.domains import models
from backend.app.main import app
from backend.app.workflows.support_agent import agent as fcs_agent
from backend.app.workflows.support_agent.tools import business_actions

client = TestClient(app)


def test_c1_admin_registration_blocked():
    """C1: Verify public /auth/register rejects role='admin' and only creates customers."""
    db.get_db().users.delete_one({"email": "hacker_admin@example.com"})
    db.get_db().users.delete_one({"email": "legit_customer@example.com"})

    # Attempt admin registration
    resp = client.post(
        "/auth/register",
        json={
            "email": "hacker_admin@example.com",
            "password": "Password123!",
            "name": "Attacker",
            "role": "admin",
        },
    )
    assert resp.status_code == 400
    assert "prohibited" in resp.json()["detail"].lower()

    # Legitimate customer registration
    customer_email = "legit_customer@example.com"
    resp_cust = client.post(
        "/auth/register",
        json={
            "email": customer_email,
            "password": "Password123!",
            "name": "Legit Customer",
        },
    )
    assert resp_cust.status_code == 202
    assert resp_cust.json() == {"detail": "If this email can be registered, you can now log in."}

    # Cleanup
    db.get_db().users.delete_one({"email": customer_email})


def test_c2_customer_order_ownership():
    """C2: Verify that cross-customer order access and business actions are rejected."""
    # Sravani is C101 (owns ORD123 and ORD125)
    # Rahul is C102 (owns ORD124)
    # 1. Direct tool-level validation: C102 acting on ORD123 (belongs to C101)
    res_cross = business_actions.create_refund_request(
        order_id="ORD123",
        reason="customer request",
        tool_context=SimpleNamespace(state={"authenticated_customer_id": "C102", "authenticated_user_role": "customer"}),
    )
    assert res_cross.get("status") == "rejected"
    assert "Ownership verification failed" in res_cross.get("reason", "")

    # Same customer acting on their own order: C101 on ORD123
    # Note: ORD123 amount is 1299 so it routes to pending_human_approval, but NOT rejected by ownership
    res_own = business_actions.create_refund_request(
        order_id="ORD123",
        reason="customer request",
        tool_context=SimpleNamespace(state={"authenticated_customer_id": "C101", "authenticated_user_role": "customer"}),
    )
    assert res_own.get("status") in ("pending_human_approval", "created", "already_requested")

    # 2. ToolContext-based ownership: simulated ADK tool context for customer C102
    ctx_c102 = SimpleNamespace(
        state={
            "authenticated_customer_id": "C102",
            "authenticated_user_role": "customer",
        }
    )
    res_ctx_blocked = business_actions.create_cancellation_request(
        order_id="ORD125",  # belongs to C101
        reason="customer request",
        tool_context=ctx_c102,
    )
    assert res_ctx_blocked.get("status") == "rejected"
    assert "Ownership verification failed" in res_ctx_blocked.get("reason", "")

    # 3. Agent order details retrieval ownership check
    order_blocked = fcs_agent.get_order_details("ORD125", tool_context=ctx_c102)
    assert "error" in order_blocked
    assert "Access denied" in order_blocked["error"]

    # Customer accessing own order
    order_allowed = fcs_agent.get_order_details("ORD124", tool_context=ctx_c102)
    assert order_allowed.get("order_id") == "ORD124"
    assert "error" not in order_allowed

    # 4. Admin bypass check: Admin can access any order
    ctx_admin = SimpleNamespace(
        state={
            "authenticated_customer_id": None,
            "authenticated_user_role": "admin",
        }
    )
    order_admin = fcs_agent.get_order_details("ORD125", tool_context=ctx_admin)
    assert order_admin.get("order_id") == "ORD125"
    assert "error" not in order_admin


def test_c7_jwt_secret_security():
    """C7: Verify JWT secret validation and failure handling."""
    # 1. Normal configured secret works and must be >= 32 chars
    secret = security.get_jwt_secret()
    assert len(secret) >= 32

    # 2. Missing secret raises RuntimeError
    old_secret = os.environ.get("JWT_SECRET")
    try:
        os.environ["JWT_SECRET"] = ""
        try:
            security.get_jwt_secret()
            assert False, "Should have raised RuntimeError for missing JWT_SECRET"
        except RuntimeError as exc:
            assert "JWT_SECRET is not configured" in str(exc)

        # 3. Insecure default placeholder raises RuntimeError in any environment
        os.environ["JWT_SECRET"] = "dev-only-secret-change-me"
        try:
            security.get_jwt_secret()
            assert False, "Should have raised RuntimeError for placeholder secret"
        except RuntimeError as exc:
            assert "Insecure or placeholder JWT_SECRET" in str(exc)

        # 4. Short secret (< 32 chars) raises RuntimeError
        os.environ["JWT_SECRET"] = "too-short-secret"
        try:
            security.get_jwt_secret()
            assert False, "Should have raised RuntimeError for short secret"
        except RuntimeError as exc:
            assert "Insecure or placeholder JWT_SECRET" in str(exc)

    finally:
        if old_secret is not None:
            os.environ["JWT_SECRET"] = old_secret
        else:
            os.environ.pop("JWT_SECRET", None)


if __name__ == "__main__":
    test_c1_admin_registration_blocked()
    print("PASS: C1 admin registration blocked test")
    test_c2_customer_order_ownership()
    print("PASS: C2 customer/order ownership test")
    test_c7_jwt_secret_security()
    print("PASS: C7 JWT secret security test")
    print("\nALL PHASE 3 SECURITY TESTS PASSED SUCCESSFULLY!")
