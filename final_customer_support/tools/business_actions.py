import json
import math
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from google.adk.tools.tool_context import ToolContext

BASE = Path(__file__).resolve().parents[1]
FIXTURE_DATA = Path(os.getenv("SUPPORTAI_FIXTURE_DIR", str(BASE / "data" / "fixtures")))
DATA = Path(os.getenv("SUPPORTAI_RUNTIME_DIR", str(BASE / "data" / "runtime")))

_actions_lock = threading.RLock()
ACTIVE_ACTION_STATUSES = {"created", "pending_human_approval", "approved"}


def _load(name):
    with _actions_lock:
        runtime_path = DATA / name
        path = runtime_path if runtime_path.exists() or name not in {"customers.json", "orders.json", "policies.json"} else FIXTURE_DATA / name
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"Failed to parse data file '{name}': {exc}") from exc


def _save(name, data):
    with _actions_lock:
        DATA.mkdir(parents=True, exist_ok=True)
        path = DATA / name
        content = json.dumps(data, indent=2)
        with tempfile.NamedTemporaryFile("w", dir=DATA, delete=False, encoding="utf-8") as tf:
            tf.write(content)
            temp_name = tf.name
        os.replace(temp_name, path)


def _new_ref(prefix):
    return f"{prefix}-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"


def _validate(order_id, requested_action, reason: str = "", tool_context: ToolContext = None):
    orders = _load("orders.json")
    policies = _load("policies.json")
    order = orders.get(order_id)
    if not order:
        return None, {"status": "rejected", "reason": f"Order '{order_id}' was not found."}

    # Ownership verification
    role = "customer"
    auth_cid = None
    if tool_context and hasattr(tool_context, "state"):
        role = tool_context.state.get("authenticated_user_role", "customer")
        auth_cid = tool_context.state.get("authenticated_customer_id")

    if role != "admin":
        if not auth_cid:
            return order, {
                "status": "rejected",
                "reason": "Ownership verification failed: Missing authenticated customer identity."
            }
        order_owner = order.get("customer_id")
        if order_owner and order_owner != auth_cid:
            return order, {
                "status": "rejected",
                "reason": f"Ownership verification failed: Order '{order_id}' belongs to customer '{order_owner}', not '{auth_cid}'."
            }

    status = order.get("status")
    if status == "Delayed":
        policy_key = "late_delivery"
    elif status == "Delivered":
        policy_key = "general_support"
    elif status == "Cancelled":
        policy_key = "cancelled_order"
    else:
        policy_key = "general_support"

    policy = policies.get(policy_key, {})
    # Customer supplied text cannot establish that a delivered item is damaged.
    # Route all delivered refund/replacement claims to human review instead.
    delivered_claim = status == "Delivered" and requested_action in {"refund", "replacement"}
    if requested_action == "refund" and not policy.get("refund_available", False) and not delivered_claim:
        return order, {"status": "rejected", "reason": "Refund is not allowed by the applicable policy."}
    if requested_action == "replacement" and not policy.get("replacement_available", False) and not delivered_claim:
        return order, {"status": "rejected", "reason": "Replacement is not allowed by the applicable policy."}
    if requested_action == "cancellation" and order.get("status") not in {"Processing", "Delayed"}:
        return order, {"status": "rejected", "reason": "This order is not in a cancellable state."}
    return order, None


def _record(action_type, order_id, result):
    actions = _load("actions.json")
    actions[result["reference"]] = {"action": action_type, "order_id": order_id, **result}
    _save("actions.json", actions)


def _existing_action(actions, action_type, order_id):
    for ref, item in actions.items():
        if item.get("order_id") != order_id or item.get("action") != action_type:
            continue
        status = item.get("status")
        if status in ACTIVE_ACTION_STATUSES:
            return {"status": "already_requested", "reference": ref}
        if status == "rejected":
            return {
                "status": "rejected",
                "reference": ref,
                "reason": item.get("review_reason") or item.get("reason", "Request was rejected."),
            }
    return None


def create_refund_request(order_id: str, reason: str, tool_context: ToolContext = None) -> dict:
    """Create one idempotent mock refund request after policy/state validation."""
    with _actions_lock:
        order, error = _validate(order_id, "refund", reason=reason, tool_context=tool_context)
        if error:
            return error
        if tool_context and tool_context.state.get("guardrail_blocked"):
            return {"status": "rejected", "reason": "Guardrail blocked the business action."}
        actions = _load("actions.json")
        existing = _existing_action(actions, "refund", order_id)
        if existing:
            return existing

        if order.get("status") == "Delivered":
            result = {
                "status": "pending_human_approval",
                "reference": _new_ref("APR"),
                "reason": reason,
                "amount": order.get("amount"),
            }
            _record("refund", order_id, result)
            return result

        amt = order.get("amount")
        # N11: only finite, positive numeric amounts are trusted for auto-creation.
        valid_amount = (
            not isinstance(amt, bool)
            and isinstance(amt, (int, float))
            and amt > 0
            and (isinstance(amt, int) or math.isfinite(amt))
        )
        if not valid_amount:
            ref = _new_ref("APR")
            result = {
                "status": "pending_human_approval",
                "reference": ref,
                "reason": f"Missing or invalid order amount: requires human verification ({reason})",
                "amount": None,
            }
            _record("refund", order_id, result)
            return result

        if amt >= 1000:
            ref = _new_ref("APR")
            result = {"status": "pending_human_approval", "reference": ref, "reason": reason, "amount": amt}
            _record("refund", order_id, result)
            return result
        result = {"status": "created", "reference": _new_ref("REF"), "reason": reason, "amount": amt}
        _record("refund", order_id, result)
        return result


def create_replacement_request(order_id: str, reason: str, tool_context: ToolContext = None) -> dict:
    """Create one mock replacement request after policy/state validation."""
    with _actions_lock:
        order, error = _validate(order_id, "replacement", reason=reason, tool_context=tool_context)
        if error:
            return error
        if tool_context and tool_context.state.get("guardrail_blocked"):
            return {"status": "rejected", "reason": "Guardrail blocked the business action."}
        actions = _load("actions.json")
        existing = _existing_action(actions, "replacement", order_id)
        if existing:
            return existing
        if order.get("status") == "Delivered":
            result = {"status": "pending_human_approval", "reference": _new_ref("APR"), "reason": reason}
            _record("replacement", order_id, result)
            return result
        result = {"status": "created", "reference": _new_ref("RPL"), "reason": reason}
        _record("replacement", order_id, result)
        return result


def create_cancellation_request(order_id: str, reason: str, tool_context: ToolContext = None) -> dict:
    """Create one mock cancellation request when the order is cancellable."""
    with _actions_lock:
        order, error = _validate(order_id, "cancellation", reason=reason, tool_context=tool_context)
        if error:
            return error
        if tool_context and tool_context.state.get("guardrail_blocked"):
            return {"status": "rejected", "reason": "Guardrail blocked the business action."}
        actions = _load("actions.json")
        existing = _existing_action(actions, "cancellation", order_id)
        if existing:
            return existing
        result = {"status": "created", "reference": _new_ref("CAN"), "reason": reason}
        _record("cancellation", order_id, result)
        return result


def create_support_case(order_id: str, issue: str, reason: str, tool_context: ToolContext = None) -> dict:
    """Record escalation intent for the backend's single ticket creator."""
    if tool_context is None or not hasattr(tool_context, "state"):
        return {"status": "rejected", "reason": "Missing authenticated session context."}
    if order_id:
        _, error = _validate(order_id, "support_case", reason=reason, tool_context=tool_context)
        if error:
            return error
    tool_context.state["escalation"] = {
        "should_escalate": True,
        "order_id": order_id,
        "issue": issue,
        "reason": reason,
    }
    return {"status": "recorded", "message": "escalation recorded"}


def list_actions(status: Optional[str] = None) -> list[dict]:
    """Retrieve action records, optionally filtered by status (N12)."""
    with _actions_lock:
        actions = _load("actions.json")
        items = list(actions.values())
        if status:
            items = [item for item in items if item.get("status") == status]
        return items


def review_action(reference: str, new_status: str, reason: str = "", reviewer: str = "") -> dict:
    """Approve or reject a pending human approval action with audit details (N12)."""
    if new_status not in {"approved", "rejected"}:
        raise ValueError("Status must be 'approved' or 'rejected'")
    with _actions_lock:
        actions = _load("actions.json")
        item = actions.get(reference)
        if not item:
            raise KeyError(f"Action '{reference}' not found")
        if item.get("status") != "pending_human_approval":
            raise ValueError(f"Action '{reference}' is not pending approval (status is '{item.get('status')}')")

        item["status"] = new_status
        item["reviewer"] = reviewer
        item["reviewed_at"] = datetime.now(timezone.utc).isoformat()
        item["review_reason"] = reason
        if new_status == "approved" and item.get("action") == "refund":
            item["resolution_reference"] = _new_ref("REF")
        actions[reference] = item
        _save("actions.json", actions)
        return item
