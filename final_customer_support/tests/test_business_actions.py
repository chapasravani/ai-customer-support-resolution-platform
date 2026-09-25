from pathlib import Path
import json

try:
    from final_customer_support.tools.business_actions import create_cancellation_request, create_refund_request
except ImportError:
    from tools.business_actions import create_cancellation_request, create_refund_request


def test_invalid_order_rejected():
    result = create_refund_request("BAD", "test")
    assert result["status"] == "rejected"


def test_cancellation_processing_order():
    result = create_cancellation_request("ORD125", "customer requested cancellation")
    assert result["status"] == "created"
    assert result["reference"].startswith("CAN-")
