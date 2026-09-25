import json
from pathlib import Path
from mcp.server.fastmcp import FastMCP

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
mcp = FastMCP("customer-support-enterprise")


def load_json(filename: str) -> dict:
    path = DATA_DIR / filename
    if not path.exists():
        return {"error": f"{filename} not found"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"error": f"{filename} contains invalid JSON"}


@mcp.tool()
def lookup_customer_mcp(customer_id: str) -> dict:
    """Retrieve a customer from the mock CRM system."""
    customers = load_json("customers.json")
    customer = customers.get(customer_id)
    if not customer:
        return {"error": f"Customer '{customer_id}' was not found."}
    return {"customer_id": customer_id, **customer}


@mcp.tool()
def lookup_order_mcp(order_id: str) -> dict:
    """Retrieve an order from the mock ERP/order system."""
    orders = load_json("orders.json")
    order = orders.get(order_id)
    if not order:
        return {"error": f"Order '{order_id}' was not found."}
    return {"order_id": order_id, **order}


@mcp.tool()
def create_support_case_mcp(customer_id: str, order_id: str, issue: str) -> dict:
    """Create a mock support case in the support system."""
    cases = load_json("support_cases.json")
    case_id = f"MCP-CASE-{len(cases)+1:04d}"
    cases[case_id] = {"case_id": case_id, "customer_id": customer_id, "order_id": order_id, "issue": issue, "status": "open"}
    (DATA_DIR / "support_cases.json").write_text(json.dumps(cases, indent=2), encoding="utf-8")
    return {"status": "created", "case_id": case_id}


if __name__ == "__main__":
    mcp.run(transport="stdio")
