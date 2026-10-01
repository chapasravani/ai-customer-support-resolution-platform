"""
Phase 4 verification test suite — Money / Business Action Safety (C3, C4, C5, C6).

How to run:
    py -3.12 -m backend.test_phase4_business_actions

What it tests:
    1. C3 — Duplicate cancellation protection:
       Calling create_cancellation_request twice on the same order returns
       already_requested with the existing reference.
    2. C4 — High-value refund approval duplicate protection:
       Calling create_refund_request on an order with amount >= 1000 returns
       pending_human_approval (APR-...) on the first call, and already_requested
       with the same reference on subsequent calls.
    3. C5 — Deterministic policy eligibility mapping:
       - Processing orders cannot receive refund or replacement (policy: general_support).
       - Delivered orders cannot be cancelled (must be in Processing or Delayed).
       - Cancelled orders cannot receive replacement.
    4. C6 — Thread-safe atomic execution & concurrency:
       Concurrent calls from multiple threads on the same order result in exactly
       one created/approved request and all others return already_requested with
       the same reference.
    5. Clean data isolation:
       Tests use an isolated temporary directory so repository data is not mutated.
"""

import json
import shutil
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from backend.app.workflows.support_agent.tools import business_actions


def _context(customer_id):
    return SimpleNamespace(state={"authenticated_customer_id": customer_id, "authenticated_user_role": "customer"})


def setup_temp_data():
    temp_dir = tempfile.mkdtemp(prefix="test_actions_")
    temp_path = Path(temp_dir)

    # Copy orders.json and policies.json from repo
    repo_data = business_actions.FIXTURE_DATA
    shutil.copy(repo_data / "orders.json", temp_path / "orders.json")
    shutil.copy(repo_data / "policies.json", temp_path / "policies.json")

    # Initialize empty actions.json and support_cases.json
    (temp_path / "actions.json").write_text("{}", encoding="utf-8")
    (temp_path / "support_cases.json").write_text("{}", encoding="utf-8")

    return temp_path


def cleanup_temp_data(temp_path: Path):
    shutil.rmtree(temp_path, ignore_errors=True)


def test_c3_duplicate_cancellation():
    print("Testing C3 — Duplicate cancellation protection...")
    temp_path = setup_temp_data()
    orig_data = business_actions.DATA
    try:
        business_actions.DATA = temp_path

        # ORD125 is in 'Processing' state, owned by C101
        res1 = business_actions.create_cancellation_request("ORD125", "cancel order", tool_context=_context("C101"))
        assert res1["status"] == "created", f"Expected 'created', got {res1}"
        assert res1["reference"].startswith("CAN-"), f"Unexpected ref: {res1['reference']}"

        # Second call must return already_requested with same ref
        res2 = business_actions.create_cancellation_request("ORD125", "cancel order again", tool_context=_context("C101"))
        assert res2["status"] == "already_requested", f"Expected 'already_requested', got {res2}"
        assert res2["reference"] == res1["reference"], f"Reference mismatch: {res2['reference']} != {res1['reference']}"

        # Verify only one cancellation is recorded in actions.json
        actions = json.loads((temp_path / "actions.json").read_text(encoding="utf-8"))
        can_entries = [v for v in actions.values() if v.get("order_id") == "ORD125" and v.get("action") == "cancellation"]
        assert len(can_entries) == 1, f"Expected 1 cancellation entry, found {len(can_entries)}"
        print("  OK - duplicate cancellation properly returns already_requested.")
    finally:
        business_actions.DATA = orig_data
        cleanup_temp_data(temp_path)


def test_c4_high_value_refund_approval_duplicate():
    print("Testing C4 — High-value refund approval duplicate protection...")
    temp_path = setup_temp_data()
    orig_data = business_actions.DATA
    try:
        business_actions.DATA = temp_path

        # ORD123 has amount=1299 (>= 1000), status='Delayed', owned by C101
        res1 = business_actions.create_refund_request("ORD123", "delayed laptop refund", tool_context=_context("C101"))
        assert res1["status"] == "pending_human_approval", f"Expected 'pending_human_approval', got {res1}"
        assert res1["reference"].startswith("APR-"), f"Unexpected ref: {res1['reference']}"
        apr_ref = res1["reference"]

        # Second call must NOT create a new APR- record; it must return already_requested
        res2 = business_actions.create_refund_request("ORD123", "delayed laptop refund retry", tool_context=_context("C101"))
        assert res2["status"] == "already_requested", f"Expected 'already_requested', got {res2}"
        assert res2["reference"] == apr_ref, f"Reference mismatch: {res2['reference']} != {apr_ref}"

        # Verify only one refund action exists for ORD123 in actions.json
        actions = json.loads((temp_path / "actions.json").read_text(encoding="utf-8"))
        apr_entries = [v for v in actions.values() if v.get("order_id") == "ORD123" and v.get("action") == "refund"]
        assert len(apr_entries) == 1, f"Expected 1 refund entry, found {len(apr_entries)}"

        # Also test normal-value refund duplicate protection (ORD124, amount 149, Delivered)
        res_norm1 = business_actions.create_refund_request("ORD124", "damaged headphones", tool_context=_context("C102"))
        assert res_norm1["status"] == "pending_human_approval", f"Expected human review, got {res_norm1}"
        assert res_norm1["reference"].startswith("APR-")

        res_norm2 = business_actions.create_refund_request("ORD124", "damaged headphones retry", tool_context=_context("C102"))
        assert res_norm2["status"] == "already_requested"
        assert res_norm2["reference"] == res_norm1["reference"]

        print("  OK - high-value approval and normal refund both prevent duplicate requests.")
    finally:
        business_actions.DATA = orig_data
        cleanup_temp_data(temp_path)


def test_c5_deterministic_policy_mapping():
    print("Testing C5 — Deterministic policy eligibility mapping...")
    temp_path = setup_temp_data()
    orig_data = business_actions.DATA
    try:
        business_actions.DATA = temp_path

        # 1. Processing order (ORD125):
        # Refund and Replacement must be rejected under general_support policy
        ref_proc = business_actions.create_refund_request("ORD125", "refund processing order", tool_context=_context("C101"))
        assert ref_proc["status"] == "rejected", f"Expected 'rejected', got {ref_proc}"
        assert "Refund is not allowed" in ref_proc["reason"]

        repl_proc = business_actions.create_replacement_request("ORD125", "replace processing order", tool_context=_context("C101"))
        assert repl_proc["status"] == "rejected", f"Expected 'rejected', got {repl_proc}"
        assert "Replacement is not allowed" in repl_proc["reason"]

        # But cancellation IS allowed for Processing order
        can_proc = business_actions.create_cancellation_request("ORD125", "cancel processing order", tool_context=_context("C101"))
        assert can_proc["status"] == "created"

        # 2. Delivered order (ORD124):
        # Cancellation must be rejected (not in cancellable state)
        can_deliv = business_actions.create_cancellation_request("ORD124", "cancel delivered order", tool_context=_context("C102"))
        assert can_deliv["status"] == "rejected", f"Expected 'rejected', got {can_deliv}"
        assert "not in a cancellable state" in can_deliv["reason"]

        # Refund and replacement ARE allowed for Delivered order (damaged_order policy)
        repl_deliv = business_actions.create_replacement_request("ORD124", "replace damaged headphones", tool_context=_context("C102"))
        assert repl_deliv["status"] == "pending_human_approval"
        assert repl_deliv["reference"].startswith("APR-")

        # 3. Add a mock Cancelled order to orders.json to verify cancelled_order policy
        orders = json.loads((temp_path / "orders.json").read_text(encoding="utf-8"))
        orders["ORD999"] = {
            "customer_id": "C101",
            "product": "Keyboard",
            "status": "Cancelled",
            "amount": 50,
        }
        (temp_path / "orders.json").write_text(json.dumps(orders, indent=2), encoding="utf-8")

        # Cancelled order cannot get replacement (replacement_available: false)
        repl_canc = business_actions.create_replacement_request("ORD999", "replace cancelled order", tool_context=_context("C101"))
        assert repl_canc["status"] == "rejected", f"Expected 'rejected', got {repl_canc}"
        assert "Replacement is not allowed" in repl_canc["reason"]

        # Cancelled order cannot be cancelled again
        can_canc = business_actions.create_cancellation_request("ORD999", "cancel again", tool_context=_context("C101"))
        assert can_canc["status"] == "rejected", f"Expected 'rejected', got {can_canc}"
        assert "not in a cancellable state" in can_canc["reason"]

        # Cancelled order CAN get refund (refund_available: true)
        ref_canc = business_actions.create_refund_request("ORD999", "refund cancelled order", tool_context=_context("C101"))
        assert ref_canc["status"] == "created", f"Expected 'created', got {ref_canc}"

        print("  OK - policy eligibility mapping is strictly deterministic across all states.")
    finally:
        business_actions.DATA = orig_data
        cleanup_temp_data(temp_path)


def test_c6_atomic_concurrency_and_retry():
    print("Testing C6 — Atomic retry / idempotency with thread locking...")
    temp_path = setup_temp_data()
    orig_data = business_actions.DATA
    try:
        business_actions.DATA = temp_path

        # Run 10 concurrent cancellation requests for ORD125 across threads
        results = []
        def send_cancellation():
            return business_actions.create_cancellation_request("ORD125", "concurrent cancel", tool_context=_context("C101"))

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(send_cancellation) for _ in range(10)]
            for f in futures:
                results.append(f.result())

        created_count = sum(1 for r in results if r["status"] == "created")
        already_count = sum(1 for r in results if r["status"] == "already_requested")

        assert created_count == 1, f"Expected exactly 1 'created', got {created_count}"
        assert already_count == 9, f"Expected 9 'already_requested', got {already_count}"

        # All results must have the exact same reference
        refs = {r["reference"] for r in results}
        assert len(refs) == 1, f"Expected exactly 1 unique reference, got {refs}"

        # Verify disk actions.json is valid JSON and has exactly 1 entry
        actions = json.loads((temp_path / "actions.json").read_text(encoding="utf-8"))
        assert len(actions) == 1, f"Expected exactly 1 action stored, got {len(actions)}"

        print("  OK - concurrent requests safely resolved to 1 creation + 9 idempotent retries.")
    finally:
        business_actions.DATA = orig_data
        cleanup_temp_data(temp_path)


def test_ownership_preservation():
    print("Testing Ownership verification preservation (C2)...")
    temp_path = setup_temp_data()
    orig_data = business_actions.DATA
    try:
        business_actions.DATA = temp_path

        # Customer C101 attempting to cancel ORD124 (owned by C102)
        res = business_actions.create_cancellation_request("ORD124", "unauthorized cancel", tool_context=_context("C101"))
        assert res["status"] == "rejected", f"Expected 'rejected', got {res}"
        assert "Ownership verification failed" in res["reason"]

        print("  OK - cross-customer action rejection preserved.")
    finally:
        business_actions.DATA = orig_data
        cleanup_temp_data(temp_path)


def main():
    print("==================================================")
    print("PHASE 4 VERIFICATION SUITE — BUSINESS ACTION SAFETY")
    print("==================================================")
    test_c3_duplicate_cancellation()
    test_c4_high_value_refund_approval_duplicate()
    test_c5_deterministic_policy_mapping()
    test_c6_atomic_concurrency_and_retry()
    test_ownership_preservation()
    print("\nALL PHASE 4 CHECKS PASSED.")


if __name__ == "__main__":
    main()
