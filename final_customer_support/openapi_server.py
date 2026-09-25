import json
from pathlib import Path
from fastapi import FastAPI

app = FastAPI(title="Customer Support Mock Enterprise API", version="1.0.0")
DATA = Path(__file__).parent / "data"

def load(name):
    return json.loads((DATA/name).read_text(encoding="utf-8"))

@app.get("/customers/{customer_id}")
def customer(customer_id: str):
    return {"customer_id": customer_id, **load("customers.json").get(customer_id, {})}

@app.get("/orders/{order_id}")
def order(order_id: str):
    return {"order_id": order_id, **load("orders.json").get(order_id, {})}

@app.post("/support-cases")
def support_case(payload: dict):
    cases = load("support_cases.json")
    case_id = f"API-CASE-{len(cases)+1:04d}"
    cases[case_id] = {"case_id": case_id, **payload, "status": "open"}
    (DATA/"support_cases.json").write_text(json.dumps(cases, indent=2), encoding="utf-8")
    return cases[case_id]
