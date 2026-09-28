import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from uuid import uuid4

from fastapi import FastAPI

app = FastAPI(title="Customer Support Mock Enterprise API", version="1.0.0")
DATA = Path(__file__).parent / "data"
_api_lock = RLock()


def load(name: str) -> dict:
    with _api_lock:
        return json.loads((DATA / name).read_text(encoding="utf-8"))


def _atomic_write(name: str, data: dict) -> None:
    path = DATA / name
    serialized = json.dumps(data, indent=2)
    with _api_lock:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=str(DATA),
            delete=False,
            encoding="utf-8",
        ) as tmp:
            tmp.write(serialized)
            tmp_path = tmp.name
        os.replace(tmp_path, str(path))


@app.get("/customers/{customer_id}")
def customer(customer_id: str):
    return {"customer_id": customer_id, **load("customers.json").get(customer_id, {})}


@app.get("/orders/{order_id}")
def order(order_id: str):
    return {"order_id": order_id, **load("orders.json").get(order_id, {})}


@app.post("/support-cases")
def support_case(payload: dict):
    with _api_lock:
        cases = load("support_cases.json")
        case_id = f"API-CASE-{len(cases)+1:04d}-{uuid4().hex[:6].upper()}"
        cases[case_id] = {"case_id": case_id, **payload, "status": "open"}
        _atomic_write("support_cases.json", cases)
        return cases[case_id]
