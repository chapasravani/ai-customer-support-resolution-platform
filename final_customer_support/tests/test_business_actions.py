import json
import shutil
from pathlib import Path
import pytest
from types import SimpleNamespace

try:
    from final_customer_support.tools import business_actions
except ImportError:
    from tools import business_actions

create_cancellation_request = business_actions.create_cancellation_request
create_refund_request = business_actions.create_refund_request
create_replacement_request = business_actions.create_replacement_request
review_action = business_actions.review_action


def _context(customer_id):
    return SimpleNamespace(state={"authenticated_customer_id": customer_id, "authenticated_user_role": "customer"})


@pytest.fixture(autouse=True)
def isolated_data_dir(monkeypatch, tmp_path):
    """Isolate business action tests so repository data files are never mutated."""
    repo_data = business_actions.FIXTURE_DATA
    shutil.copy(repo_data / "orders.json", tmp_path / "orders.json")
    shutil.copy(repo_data / "policies.json", tmp_path / "policies.json")
    (tmp_path / "actions.json").write_text("{}", encoding="utf-8")
    (tmp_path / "support_cases.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(business_actions, "DATA", tmp_path)


def test_invalid_order_rejected():
    result = create_refund_request("BAD", "test")
    assert result["status"] == "rejected"


def test_cancellation_processing_order():
    result = create_cancellation_request("ORD125", "customer requested cancellation", tool_context=_context("C101"))
    assert result["status"] == "created"
    assert result["reference"].startswith("CAN-")

    # C3: Duplicate cancellation request must return already_requested
    dup = create_cancellation_request("ORD125", "customer requested cancellation again", tool_context=_context("C101"))
    assert dup["status"] == "already_requested"
    assert dup["reference"] == result["reference"]


def test_high_value_refund_approval_idempotency():
    # C4: High-value refund (amount >= 1000) creates APR- then returns already_requested
    res1 = create_refund_request("ORD123", "delayed laptop refund", tool_context=_context("C101"))
    assert res1["status"] == "pending_human_approval"
    assert res1["reference"].startswith("APR-")

    res2 = create_refund_request("ORD123", "delayed laptop refund retry", tool_context=_context("C101"))
    assert res2["status"] == "already_requested"
    assert res2["reference"] == res1["reference"]


def test_approved_refund_cannot_be_requested_again():
    first = create_refund_request("ORD123", "refund", tool_context=_context("C101"))
    review_action(first["reference"], "approved", reason="verified", reviewer="admin")

    retry = create_refund_request("ORD123", "refund again", tool_context=_context("C101"))

    assert retry["reference"] == first["reference"]
    assert retry["status"] == "already_requested"
    assert len(business_actions._load("actions.json")) == 1


def test_rejected_refund_is_returned_without_creating_another_action():
    first = create_refund_request("ORD123", "refund", tool_context=_context("C101"))
    review_action(first["reference"], "rejected", reason="already compensated", reviewer="admin")

    retry = create_refund_request("ORD123", "refund again", tool_context=_context("C101"))

    assert retry == {
        "status": "rejected",
        "reference": first["reference"],
        "reason": "already compensated",
    }
    assert len(business_actions._load("actions.json")) == 1


def test_approved_cancellation_is_not_created_again():
    first = create_cancellation_request("ORD125", "cancel", tool_context=_context("C101"))
    actions = business_actions._load("actions.json")
    actions[first["reference"]]["status"] = "approved"
    business_actions._save("actions.json", actions)

    retry = create_cancellation_request("ORD125", "cancel again", tool_context=_context("C101"))

    assert retry["reference"] == first["reference"]
    assert retry["status"] == "already_requested"
    assert len(business_actions._load("actions.json")) == 1


def test_approved_replacement_is_not_created_again():
    first = create_replacement_request("ORD124", "replace", tool_context=_context("C102"))
    review_action(first["reference"], "approved", reason="verified", reviewer="admin")

    retry = create_replacement_request("ORD124", "replace again", tool_context=_context("C102"))

    assert retry["reference"] == first["reference"]
    assert retry["status"] == "already_requested"
    assert len(business_actions._load("actions.json")) == 1


def test_rejected_cancellation_returns_rejection_without_new_action():
    first = create_cancellation_request("ORD125", "cancel", tool_context=_context("C101"))
    actions = business_actions._load("actions.json")
    actions[first["reference"]].update(status="rejected", review_reason="shipment already dispatched")
    business_actions._save("actions.json", actions)

    retry = create_cancellation_request("ORD125", "cancel again", tool_context=_context("C101"))

    assert retry == {
        "status": "rejected",
        "reference": first["reference"],
        "reason": "shipment already dispatched",
    }
    assert len(business_actions._load("actions.json")) == 1


def test_policy_eligibility_mapping():
    # C5: Processing order cannot get refund or replacement
    ref_proc = create_refund_request("ORD125", "refund processing", tool_context=_context("C101"))
    assert ref_proc["status"] == "rejected"
    assert "Refund is not allowed" in ref_proc["reason"]

    repl_proc = create_replacement_request("ORD125", "replace processing", tool_context=_context("C101"))
    assert repl_proc["status"] == "rejected"
    assert "Replacement is not allowed" in repl_proc["reason"]

    # Delivered order cannot be cancelled
    can_deliv = create_cancellation_request("ORD124", "cancel delivered", tool_context=_context("C102"))
    assert can_deliv["status"] == "rejected"
    assert "not in a cancellable state" in can_deliv["reason"]

    # Delivered order replacement claims require human review.
    repl_deliv = create_replacement_request("ORD124", "replace damaged", tool_context=_context("C102"))
    assert repl_deliv["status"] == "pending_human_approval"
    assert repl_deliv["reference"].startswith("APR-")


@pytest.mark.parametrize("reason", ["customer says damaged", "item is not damaged, just dislike"])
@pytest.mark.parametrize("action", ["refund", "replacement"])
def test_delivered_refund_and_replacement_require_human_approval(action, reason):
    request = create_refund_request if action == "refund" else create_replacement_request

    result = request("ORD124", reason, tool_context=_context("C102"))

    assert result["status"] == "pending_human_approval"
    assert result["reason"] == reason
    assert len(business_actions._load("actions.json")) == 1


@pytest.mark.parametrize("amount", [None, "500", True, float("nan"), float("inf"), -5, 0])
def test_invalid_refund_amount_never_auto_creates(amount):
    orders = business_actions._load("orders.json")
    orders["ORD123"]["amount"] = amount
    business_actions._save("orders.json", orders)

    result = create_refund_request("ORD123", "refund", tool_context=_context("C101"))

    assert result["status"] == "pending_human_approval"


def test_missing_identity_rejected():
    # N2: Operations without identity fail explicitly
    res = create_cancellation_request("ORD125", "cancel without identity")
    assert res["status"] == "rejected"
    assert "Missing authenticated customer identity" in res["reason"]


def test_support_case_records_intent_without_writing_or_minting_a_ticket_id():
    tool_context = _context("C101")
    cases_path = business_actions.DATA / "support_cases.json"
    before = cases_path.read_text(encoding="utf-8")
    result = business_actions.create_support_case(
        "ORD123", "delivery issue", "customer requests human help", tool_context=tool_context
    )
    assert result == {"status": "recorded", "message": "escalation recorded"}
    assert tool_context.state["escalation"] == {
        "should_escalate": True,
        "order_id": "ORD123",
        "issue": "delivery issue",
        "reason": "customer requests human help",
    }
    assert "reference" not in result and cases_path.read_text(encoding="utf-8") == before
