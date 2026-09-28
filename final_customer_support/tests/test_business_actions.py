import json
import shutil
from pathlib import Path
import pytest

try:
    from final_customer_support.tools import business_actions
except ImportError:
    from tools import business_actions

create_cancellation_request = business_actions.create_cancellation_request
create_refund_request = business_actions.create_refund_request
create_replacement_request = business_actions.create_replacement_request


@pytest.fixture(autouse=True)
def isolated_data_dir(monkeypatch, tmp_path):
    """Isolate business action tests so repository data files are never mutated."""
    repo_data = business_actions.BASE / "data"
    shutil.copy(repo_data / "orders.json", tmp_path / "orders.json")
    shutil.copy(repo_data / "policies.json", tmp_path / "policies.json")
    (tmp_path / "actions.json").write_text("{}", encoding="utf-8")
    (tmp_path / "support_cases.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(business_actions, "DATA", tmp_path)


def test_invalid_order_rejected():
    result = create_refund_request("BAD", "test")
    assert result["status"] == "rejected"


def test_cancellation_processing_order():
    result = create_cancellation_request("ORD125", "customer requested cancellation")
    assert result["status"] == "created"
    assert result["reference"].startswith("CAN-")

    # C3: Duplicate cancellation request must return already_requested
    dup = create_cancellation_request("ORD125", "customer requested cancellation again")
    assert dup["status"] == "already_requested"
    assert dup["reference"] == result["reference"]


def test_high_value_refund_approval_idempotency():
    # C4: High-value refund (amount >= 1000) creates APR- then returns already_requested
    res1 = create_refund_request("ORD123", "delayed laptop refund")
    assert res1["status"] == "pending_human_approval"
    assert res1["reference"].startswith("APR-")

    res2 = create_refund_request("ORD123", "delayed laptop refund retry")
    assert res2["status"] == "already_requested"
    assert res2["reference"] == res1["reference"]


def test_policy_eligibility_mapping():
    # C5: Processing order cannot get refund or replacement
    ref_proc = create_refund_request("ORD125", "refund processing")
    assert ref_proc["status"] == "rejected"
    assert "Refund is not allowed" in ref_proc["reason"]

    repl_proc = create_replacement_request("ORD125", "replace processing")
    assert repl_proc["status"] == "rejected"
    assert "Replacement is not allowed" in repl_proc["reason"]

    # Delivered order cannot be cancelled
    can_deliv = create_cancellation_request("ORD124", "cancel delivered")
    assert can_deliv["status"] == "rejected"
    assert "not in a cancellable state" in can_deliv["reason"]

    # Delivered order can receive replacement
    repl_deliv = create_replacement_request("ORD124", "replace damaged")
    assert repl_deliv["status"] == "created"
    assert repl_deliv["reference"].startswith("RPL-")
