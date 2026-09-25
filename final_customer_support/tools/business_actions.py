import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from google.adk.tools.tool_context import ToolContext

BASE = Path(__file__).resolve().parents[1]
DATA = BASE / "data"


def _load(name):
    path = DATA / name
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save(name, data):
    (DATA / name).write_text(json.dumps(data, indent=2), encoding="utf-8")


def _new_ref(prefix):
    return f"{prefix}-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"


def _validate(order_id, requested_action):
    orders = _load("orders.json")
    policies = _load("policies.json")
    order = orders.get(order_id)
    if not order:
        return None, {"status": "rejected", "reason": f"Order '{order_id}' was not found."}
    policy_key = "damaged_order" if requested_action in {"refund", "replacement"} else "late_delivery" if order.get("status") == "Delayed" else "cancelled_order" if order.get("status") == "Cancelled" else "general_support"
    policy = policies.get(policy_key, {})
    if requested_action == "refund" and not policy.get("refund_available", False):
        return order, {"status": "rejected", "reason": "Refund is not allowed by the applicable policy."}
    if requested_action == "replacement" and not policy.get("replacement_available", False):
        return order, {"status": "rejected", "reason": "Replacement is not allowed by the applicable policy."}
    if requested_action == "cancellation" and order.get("status") not in {"Processing", "Delayed"}:
        return order, {"status": "rejected", "reason": "This order is not in a cancellable state."}
    return order, None


def _record(action_type, order_id, result):
    actions = _load("actions.json")
    actions[result["reference"]] = {"action": action_type, "order_id": order_id, **result}
    _save("actions.json", actions)


def create_refund_request(order_id: str, reason: str, tool_context: ToolContext = None) -> dict:
    """Create one idempotent mock refund request after policy/state validation."""
    order, error = _validate(order_id, "refund")
    if error:
        return error
    if tool_context and tool_context.state.get("guardrail_blocked"):
        return {"status": "rejected", "reason": "Guardrail blocked the business action."}
    if order.get("amount", 0) >= 1000:
        ref = _new_ref("APR")
        result = {"status": "pending_human_approval", "reference": ref, "reason": reason, "amount": order.get("amount", 0)}
        _record("refund", order_id, result)
        return result
    actions = _load("actions.json")
    for ref, item in actions.items():
        if item.get("order_id") == order_id and item.get("action") == "refund" and item.get("status") in {"created", "pending_human_approval"}:
            return {"status": "already_requested", "reference": ref}
    result = {"status": "created", "reference": _new_ref("REF"), "reason": reason, "amount": order.get("amount", 0)}
    _record("refund", order_id, result)
    return result


def create_replacement_request(order_id: str, reason: str, tool_context: ToolContext = None) -> dict:
    """Create one mock replacement request after policy/state validation."""
    order, error = _validate(order_id, "replacement")
    if error:
        return error
    if tool_context and tool_context.state.get("guardrail_blocked"):
        return {"status": "rejected", "reason": "Guardrail blocked the business action."}
    actions = _load("actions.json")
    for ref, item in actions.items():
        if item.get("order_id") == order_id and item.get("action") == "replacement" and item.get("status") in {"created", "pending_human_approval"}:
            return {"status": "already_requested", "reference": ref}
    result = {"status": "created", "reference": _new_ref("RPL"), "reason": reason}
    _record("replacement", order_id, result)
    return result


def create_cancellation_request(order_id: str, reason: str, tool_context: ToolContext = None) -> dict:
    """Create one mock cancellation request when the order is cancellable."""
    order, error = _validate(order_id, "cancellation")
    if error:
        return error
    if tool_context and tool_context.state.get("guardrail_blocked"):
        return {"status": "rejected", "reason": "Guardrail blocked the business action."}
    result = {"status": "created", "reference": _new_ref("CAN"), "reason": reason}
    _record("cancellation", order_id, result)
    return result


def create_support_case(customer_id: str, order_id: str, issue: str, reason: str, tool_context: ToolContext = None) -> dict:
    """Create a mock human-support case and return its reference."""
    cases = _load("support_cases.json")
    ref = _new_ref("CASE")
    case = {"case_id": ref, "customer_id": customer_id, "order_id": order_id, "issue": issue, "reason": reason, "status": "open", "created_at": datetime.now(timezone.utc).isoformat()}
    cases[ref] = case
    _save("support_cases.json", cases)
    return {"status": "created", "reference": ref, "case": case}
