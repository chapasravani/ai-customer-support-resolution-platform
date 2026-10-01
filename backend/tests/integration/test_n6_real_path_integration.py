import asyncio
import json
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from google.adk.models import BaseLlm, LlmResponse
from google.genai import types

from backend.app.core import security
from backend.app.infrastructure import db
from backend.app.domains import models
from backend.app.main import app
from backend.app.workflows import adk_bridge
from backend.app.workflows.support_agent import agent as fcs_agent

client = TestClient(app)


class SmartStubLlm(BaseLlm):
    """Stub LLM that emits a get_order_details call for ORD123 (owned by C101)."""
    model: str = "smart-stub-llm"

    async def generate_content_async(self, req, stream=False):
        tools = req.tools_dict or {}

        # Check if function response was already returned in request
        has_resp = False
        if req.contents:
            for c in req.contents:
                for p in getattr(c, "parts", []):
                    if getattr(p, "function_response", None):
                        has_resp = True

        if "get_order_details" in tools and not has_resp:
            yield LlmResponse(content=types.Content(
                role="model",
                parts=[types.Part(function_call=types.FunctionCall(name="get_order_details", args={"order_id": "ORD123"}))]
            ))
            return

        schema = getattr(req.config, "response_schema", None)
        if schema:
            sname = getattr(schema, "__name__", "")
            if "Investigation" in sname:
                text = json.dumps({
                    "issue": "delayed delivery",
                    "cause": "carrier delay",
                    "facts": ["order delayed"],
                    "missing_information": [],
                    "applicable_policy": "late_delivery",
                    "resolution_options": ["wait"],
                    "confidence": "high",
                    "requires_human": False,
                })
            elif "Resolution" in sname:
                text = json.dumps({
                    "resolution_type": "RECOMMEND",
                    "action": "no action",
                    "resolution": "wait for delivery",
                    "reason": "order is in transit",
                    "eligible": False,
                    "action_reference": "",
                    "requires_human": False,
                })
            elif "Escalation" in sname:
                text = json.dumps({
                    "should_escalate": False,
                    "case_id": "",
                    "priority": "low",
                    "customer_id": "C102",
                    "order_id": "ORD123",
                    "reason": "no escalation needed",
                    "verified_facts": [],
                    "investigation_summary": "",
                    "applicable_policy": "",
                    "attempted_actions": [],
                    "recommended_action": "none",
                })
            else:
                text = "{}"
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))
            return

        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="Checked order.")]))


def test_n6_real_path_identity_enforcement(monkeypatch):
    """
    N6: Verify end-to-end integration via POST /chat/message:
    Real JWT -> FastAPI route -> real adk_bridge -> real InMemorySessionService -> real get_order_details.
    Customer C102 must NOT be able to view ORD123 (owned by C101).
    Session state must retain authenticated_customer_id.
    """
    test_email = "test_c102@example.com"
    db.get_db().users.delete_one({"email": test_email})

    user = models.create_user(
        email=test_email,
        hashed_password=security.hash_password("SecurePassword123!"),
        name="Test C102",
        role="customer",
        customer_id="C102"
    )
    user_id = str(user["_id"])
    token = security.create_access_token(user_id=user_id, role="customer")
    convo = models.create_conversation(user_id)
    convo_id = str(convo["_id"])

    # Seed hostile legacy state to prove the authenticated ID takes precedence.
    asyncio.run(adk_bridge._session_service.create_session(
        app_name=adk_bridge.APP_NAME,
        user_id=user_id,
        session_id=convo_id,
        state={
            "authenticated_customer_id": "C102",
            "authenticated_user_role": "customer",
            "customer_id": "C101",
        },
    ))

    # Wire up the stub model on root agent
    stub_llm = SmartStubLlm()
    root, agents_dict = fcs_agent.build_agent_tree(target_model=stub_llm)
    monkeypatch.setattr(adk_bridge, "_primary_runner", adk_bridge.Runner(
        app_name=adk_bridge.APP_NAME,
        agent=root,
        session_service=adk_bridge._session_service,
    ))

    # Send chat message requesting order ORD123
    resp = client.post(
        "/chat/message",
        json={"message": "Please check my order ORD123", "conversation_id": convo_id},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["conversation_id"] == convo_id

    # Check the real session in adk_bridge session_service
    session = asyncio.run(adk_bridge._session_service.get_session(
        app_name=adk_bridge.APP_NAME,
        user_id=user_id,
        session_id=convo_id
    ))
    assert session is not None

    # C2 verification: authenticated_customer_id MUST persist in session.state
    assert session.state.get("authenticated_customer_id") == "C102", (
        f"C2 violation: authenticated_customer_id was lost from session.state! State is: {session.state}"
    )
    assert session.state.get("customer_id") == "C101"

    # Inspect the actual ADK tool result, not an agent summary that can omit the order.
    def tool_result(session):
        for event in session.events:
            for part in getattr(getattr(event, "content", None), "parts", []) or []:
                response = getattr(part, "function_response", None)
                if response and response.name == "get_order_details":
                    return response.response
        return None

    denied_result = tool_result(session)
    assert denied_result is not None
    assert "Access denied" in str(denied_result), denied_result

    # Legacy state alone must never authenticate a caller when authenticated ID is absent.
    legacy_only_result = fcs_agent.get_order_details(
        "ORD123",
        tool_context=SimpleNamespace(state={"authenticated_user_role": "customer", "customer_id": "C101"}),
    )
    assert "Access denied" in str(legacy_only_result), legacy_only_result

    # Positive control: the actual owner receives the same order record.
    owner = models.create_user(
        email="test_c101@example.com",
        hashed_password=security.hash_password("SecurePassword123!"),
        name="Test C101",
        role="customer",
        customer_id="C101",
    )
    owner_id = str(owner["_id"])
    owner_token = security.create_access_token(user_id=owner_id, role="customer")
    owner_resp = client.post(
        "/chat/message",
        json={"message": "Please check my order ORD123"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert owner_resp.status_code == 200
    owner_session = asyncio.run(adk_bridge._session_service.get_session(
        app_name=adk_bridge.APP_NAME,
        user_id=owner_id,
        session_id=owner_resp.json()["conversation_id"],
    ))
    owner_result = tool_result(owner_session)
    assert owner_result is not None and owner_result.get("order_id") == "ORD123", owner_result

    # Cleanup
    db.get_db().users.delete_one({"email": test_email})
    db.get_db().users.delete_one({"email": "test_c101@example.com"})
