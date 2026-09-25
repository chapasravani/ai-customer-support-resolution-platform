from typing import Any
from google.adk.tools import LongRunningFunctionTool


def start_carrier_investigation(order_id: str, reason: str) -> dict[str, Any]:
    """Start a mock external carrier investigation and return an operation reference."""
    return {
        "status": "pending",
        "operation_id": f"CARRIER-{order_id}",
        "order_id": order_id,
        "reason": reason,
        "message": "Carrier investigation started. The client can resume with the operation result."
    }


carrier_investigation_tool = LongRunningFunctionTool(func=start_carrier_investigation)
