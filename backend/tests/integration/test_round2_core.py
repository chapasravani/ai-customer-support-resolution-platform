import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend import auth, db, models
from backend.main import app
from backend.api_schemas import ChatMessageRequest
from backend.routes import chat
from pymongo.errors import DuplicateKeyError


client = TestClient(app)


def _customer(email):
    user = models.create_user(email, "hash", "Round two", "customer")
    return user, {"Authorization": f"Bearer {auth.create_access_token(str(user['_id']), role='customer')}"}


def test_r6_concurrent_request_id_is_claimed_once():
    user, headers = _customer("r6-concurrent@example.com")
    convo = models.create_conversation(str(user["_id"]))
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    async def blocked_workflow(**kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        await asyncio.to_thread(release.wait, 5)
        return {"response": "done", "success": True, "escalation": {}}

    try:
        with patch("backend.routes.chat.run_support_workflow", side_effect=blocked_workflow):
            with ThreadPoolExecutor(max_workers=1) as pool:
                first = pool.submit(client.post, "/chat/message", headers=headers, json={
                    "message": "help", "conversation_id": str(convo["_id"]), "request_id": "same-id",
                })
                assert entered.wait(3)
                second = client.post("/chat/message", headers=headers, json={
                    "message": "help", "conversation_id": str(convo["_id"]), "request_id": "same-id",
                })
                release.set()
                assert first.result(timeout=5).status_code == 200
        assert second.status_code == 409
        assert calls == 1
    finally:
        release.set()
        db.get_db().users.delete_one({"_id": user["_id"]})
        db.get_db().conversations.delete_one({"_id": convo["_id"]})


def test_r6_failed_retry_reuses_user_message_and_is_per_user():
    user_a, headers_a = _customer("r6-retry-a@example.com")
    user_b, headers_b = _customer("r6-retry-b@example.com")
    convo = models.create_conversation(str(user_a["_id"]))
    calls = 0

    async def fail_then_succeed(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"response": "try later", "success": False, "error_type": "unavailable"}
        return {"response": f"done {calls}", "success": True, "escalation": {}}

    try:
        with patch("backend.routes.chat.run_support_workflow", side_effect=fail_then_succeed):
            first = client.post("/chat/message", headers=headers_a, json={
                "message": "help", "conversation_id": str(convo["_id"]), "request_id": "retry-id",
            })
            retry = client.post("/chat/message", headers=headers_a, json={
                "message": "help", "conversation_id": str(convo["_id"]), "request_id": "retry-id",
            })
            assert calls == 2
            other = client.post("/chat/message", headers=headers_b, json={"message": "hello", "request_id": "retry-id"})
        messages = models.get_conversation(str(convo["_id"]))["messages"]
        assert first.status_code == 200 and first.json()["error_type"] == "unavailable"
        assert retry.status_code == 200 and retry.json()["response"] == "done 2"
        assert calls == 3
        assert len([m for m in messages if m["role"] == "user"]) == 1

        # The unique key is (user_id, request_id), so another user may use this ID independently.
        assert other.status_code == 200 and other.json()["response"] == "done 3"
    finally:
        for user in (user_a, user_b):
            db.get_db().users.delete_one({"_id": user["_id"]})
        db.get_db().conversations.delete_many({"user_id": {"$in": [user_a["_id"], user_b["_id"]]}})


def test_r8_escalation_reply_uses_active_ticket_id_and_reopens_resolved():
    user, headers = _customer("r8-ticket@example.com")
    convo = models.create_conversation(str(user["_id"]))
    convo_id = str(convo["_id"])
    old = models.create_ticket("CASE-OLD", str(user["_id"]), "old", conversation_id=convo_id, status="resolved")
    result = {"response": "Human escalation requested.", "success": True, "escalation": {"should_escalate": True}}
    try:
        with patch("backend.routes.chat.run_support_workflow", return_value=result):
            response = client.post("/chat/message", headers=headers, json={"message": "escalate", "conversation_id": convo_id})
        docs = list(db.get_db().tickets.find({"conversation_id": models._oid(convo_id)}))
        new = [ticket for ticket in docs if ticket["status"] == "open"]
        assert len(new) == 1
        assert new[0]["ticket_id"] in response.json()["response"]
    finally:
        db.get_db().users.delete_one({"_id": user["_id"]})
        db.get_db().conversations.delete_one({"_id": convo["_id"]})
        db.get_db().tickets.delete_many({"conversation_id": models._oid(convo_id)})


def test_r8_concurrent_ticket_upsert_returns_unique_winner(monkeypatch):
    winner = {"ticket_id": "CASE-WINNER", "status": "open"}

    class RacingTickets:
        def find_one_and_update(self, *args, **kwargs):
            raise DuplicateKeyError("active ticket key won by concurrent request")

        def find_one(self, query, sort=None):
            assert query["conversation_id"] == "conversation-race"
            return winner

    monkeypatch.setattr(models, "get_db", lambda: SimpleNamespace(tickets=RacingTickets()))
    result = models.find_or_create_open_ticket(
        "CASE-LOSER", "user-race", "issue", "ORD123", "conversation-race"
    )
    assert result is winner


def test_r8_active_ticket_key_has_unique_sparse_index():
    db.ensure_indexes()
    indexes = models.get_db().tickets.index_information()
    active_index = next(
        details for details in indexes.values()
        if details.get("key") == [("active_ticket_key", 1)]
    )
    assert active_index["unique"] is True
    assert active_index["sparse"] is True


def test_r8_unique_ticket_key_only_applies_to_conversation_tickets():
    first = models.create_ticket("CASE-NOCONVO-1", "user-a", "issue", status="resolved")
    second = models.create_ticket("CASE-NOCONVO-2", "user-b", "issue", status="resolved")
    conversation = models.create_conversation("user-c")
    try:
        assert models.update_ticket_status(first["ticket_id"], "open")
        assert models.update_ticket_status(second["ticket_id"], "open")
        assert "active_ticket_key" not in models.get_ticket(first["ticket_id"])
        assert "active_ticket_key" not in models.get_ticket(second["ticket_id"])

        linked = models.create_ticket(
            "CASE-CONVO", "user-c", "issue", conversation_id=str(conversation["_id"])
        )
        assert linked["active_ticket_key"] == str(conversation["_id"])
    finally:
        db.get_db().tickets.delete_many({"ticket_id": {"$in": [
            "CASE-NOCONVO-1", "CASE-NOCONVO-2", "CASE-CONVO"
        ]}})
        db.get_db().conversations.delete_one({"_id": conversation["_id"]})


def test_r9_ticket_update_failure_is_reported_and_request_stays_retryable():
    user, headers = _customer("r9-ticket-error@example.com")
    convo = models.create_conversation(str(user["_id"]))
    convo_id = str(convo["_id"])
    result = {"response": "We are escalating this.", "success": True, "escalation": {"should_escalate": True}}
    try:
        with patch("backend.routes.chat.run_support_workflow", return_value=result), \
             patch("backend.models.update_ticket_issue", side_effect=RuntimeError("update failed")):
            response = client.post("/chat/message", headers=headers, json={
                "message": "please escalate", "conversation_id": convo_id, "request_id": "r9-retryable",
            })
        request = db.get_db().chat_requests.find_one({"user_id": user["_id"], "request_id": "r9-retryable"})
        saved = models.get_conversation(convo_id)
        assert response.status_code == 200
        assert response.json()["error_type"] == "ticket_creation_failed"
        assert request["status"] == "failed"
        assert not any(m["role"] == "assistant" for m in saved["messages"])
        assert next(m for m in saved["messages"] if m["role"] == "user")["failed"] is True
    finally:
        db.get_db().users.delete_one({"_id": user["_id"]})
        db.get_db().conversations.delete_one({"_id": convo["_id"]})
        db.get_db().tickets.delete_many({"conversation_id": models._oid(convo_id)})
        db.get_db().chat_requests.delete_many({"user_id": user["_id"]})


def test_r12_no_tool_accepts_customer_id_override():
    import inspect
    from google.adk.tools import FunctionTool
    from final_customer_support import agent
    from final_customer_support.tools import business_actions

    assert "customer_id" not in inspect.signature(agent.get_customer_details).parameters
    assert "customer_id" not in inspect.signature(agent.initialize_support_state).parameters
    for tool in (
        business_actions.create_refund_request,
        business_actions.create_replacement_request,
        business_actions.create_cancellation_request,
        business_actions.create_support_case,
    ):
        assert "customer_id" not in inspect.signature(tool).parameters
        assert "kwargs" not in inspect.signature(tool).parameters
        declaration = FunctionTool(func=tool)._get_declaration()
        assert "customer_id" not in str(declaration)


def test_r17_empty_final_response_is_an_error():
    from unittest.mock import AsyncMock, MagicMock
    from backend import adk_bridge

    async def events(**kwargs):
        if False:
            yield None

    runner = MagicMock()
    runner.run_async = events
    fake_session = MagicMock(state={})
    with patch.object(adk_bridge, "_get_or_create_session", new=AsyncMock(return_value=fake_session)), \
         patch.object(adk_bridge, "_primary_runner", runner), \
         patch.object(adk_bridge, "_fallback_runner", runner), \
         patch.object(adk_bridge._session_service, "get_session", new=AsyncMock(return_value=fake_session)):
        result = asyncio.run(adk_bridge.run_support_workflow("u", "s", "hi"))
    assert result["success"] is False
    assert result["error_type"] == "empty_response"


def test_r4_action_then_service_error_is_never_retried():
    from unittest.mock import AsyncMock, MagicMock
    from google.genai import types
    from google.adk.events.event import Event
    from backend import adk_bridge

    action_calls = 0

    class StubRunner:
        async def run_async(self, **kwargs):
            nonlocal action_calls
            action_calls += 1
            yield Event(
                author="business_action_agent",
                content=types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(
                    name="create_refund_request", args={"order_id": "ORD123", "reason": "approved"},
                ))]),
            )
            raise RuntimeError("503 unavailable")

    primary, fallback = StubRunner(), StubRunner()
    fake_session = MagicMock(state={})
    with patch.object(adk_bridge, "_get_or_create_session", new=AsyncMock(return_value=fake_session)), \
         patch.object(adk_bridge, "_primary_runner", primary), \
         patch.object(adk_bridge, "_fallback_runner", fallback), \
         patch.object(adk_bridge._session_service, "get_session", new=AsyncMock(return_value=fake_session)), \
         patch.object(adk_bridge.asyncio, "sleep", new=AsyncMock()):
        result = asyncio.run(adk_bridge.run_support_workflow("u", "s-r4", "refund"))
    assert result["success"] is False
    assert result["error_type"] == "partial_after_action"
    assert action_calls == 1


def test_r18_session_hydration_error_fails_workflow():
    from backend import adk_bridge

    with patch.object(adk_bridge, "_get_or_create_session", side_effect=RuntimeError("history store down")):
        result = asyncio.run(adk_bridge.run_support_workflow("u", "s-r18", "hello"))
    assert result["success"] is False
    assert result["error_type"] == "history_unavailable"


def test_r19_hydration_skips_failed_turns():
    from google.adk.sessions import InMemorySessionService
    from backend import adk_bridge

    service = InMemorySessionService()
    convo = models.create_conversation("r19-user")
    cid = str(convo["_id"])
    failed = models.add_message(cid, "user", "failed request")
    models.set_message_failed(cid, failed["id"], True)
    models.add_message(cid, "assistant", "answer")
    models.add_message(cid, "user", "current request")
    try:
        with patch.object(adk_bridge, "_session_service", service):
            session = asyncio.run(adk_bridge._get_or_create_session("r19-user", cid))
        text = [part.text for event in session.events for part in getattr(getattr(event, "content", None), "parts", []) or [] if part.text]
        assert "failed request" not in text
        assert "answer" in text
    finally:
        db.get_db().conversations.delete_one({"_id": convo["_id"]})


def test_r20_corrupt_agent_data_raises_without_changing_file(tmp_path, monkeypatch):
    from final_customer_support import agent

    path = tmp_path / "orders.json"
    original = "{invalid json"
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(agent, "DATA_DIR", tmp_path)
    try:
        agent.load_json("orders.json")
        assert False, "Corrupt JSON must raise"
    except ValueError as exc:
        assert "invalid JSON" in str(exc)
    assert path.read_text(encoding="utf-8") == original


def test_r22_same_identity_does_not_append_empty_session_delta():
    from google.adk.sessions import InMemorySessionService
    from backend import adk_bridge

    service = InMemorySessionService()
    state = {"authenticated_customer_id": "C101"}
    with patch.object(adk_bridge, "_session_service", service):
        first = asyncio.run(adk_bridge._get_or_create_session("r22-user", "r22-session", state))
        second = asyncio.run(adk_bridge._get_or_create_session("r22-user", "r22-session", state))
    assert len(second.events) == len(first.events)


def test_f1_assistant_save_failure_releases_request_for_retry():
    request_id = "f1-save-" + uuid4().hex
    user, headers = _customer(f"{request_id}@example.com")
    convo = models.create_conversation(str(user["_id"]))
    workflow_calls = 0
    original_add_message = models.add_message
    fail_assistant_once = True

    def add_message_then_fail_once(*args, **kwargs):
        nonlocal fail_assistant_once
        if args[1] == "assistant" and fail_assistant_once:
            fail_assistant_once = False
            raise RuntimeError("assistant persistence failed")
        return original_add_message(*args, **kwargs)

    async def workflow(**kwargs):
        nonlocal workflow_calls
        workflow_calls += 1
        return {"response": "resolved", "success": True, "escalation": {}}

    with patch("backend.routes.chat.models.add_message", side_effect=add_message_then_fail_once), \
         patch("backend.routes.chat.run_support_workflow", side_effect=workflow):
        with pytest.raises(RuntimeError, match="assistant persistence failed"):
            client.post("/chat/message", headers=headers, json={
                "message": "help", "conversation_id": str(convo["_id"]), "request_id": request_id,
            })
        retry = client.post("/chat/message", headers=headers, json={
            "message": "help", "conversation_id": str(convo["_id"]), "request_id": request_id,
        })

    saved = models.get_conversation(str(convo["_id"]))
    request = db.get_db().chat_requests.find_one({"user_id": user["_id"], "request_id": request_id})
    assert retry.status_code == 200
    assert workflow_calls == 2
    assert len([m for m in saved["messages"] if m["role"] == "user"]) == 1
    assert request["status"] == "done"


def test_f1_stale_in_progress_request_can_be_retried():
    request_id = "f1-stale-" + uuid4().hex
    user, headers = _customer(f"{request_id}@example.com")
    convo = models.create_conversation(str(user["_id"]))
    db.get_db().chat_requests.insert_one({
        "user_id": user["_id"], "request_id": request_id,
        "conversation_id": str(convo["_id"]), "status": "in_progress",
        "response": "", "created_at": models._now() - timedelta(minutes=6),
    })
    calls = 0

    async def workflow(**kwargs):
        nonlocal calls
        calls += 1
        return {"response": "retried", "success": True, "escalation": {}}

    with patch("backend.routes.chat.run_support_workflow", side_effect=workflow):
        response = client.post("/chat/message", headers=headers, json={
            "message": "help", "conversation_id": str(convo["_id"]), "request_id": request_id,
        })

    assert response.status_code == 200
    assert calls == 1


def test_f2_clean_stream_after_action_is_not_retried():
    from unittest.mock import AsyncMock, MagicMock
    from google.adk.events.event import Event
    from google.genai import types
    from backend import adk_bridge

    calls = 0

    class StubRunner:
        async def run_async(self, **kwargs):
            nonlocal calls
            calls += 1
            yield Event(
                author="business_action_agent",
                content=types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(
                    name="create_refund_request", args={"order_id": "ORD123", "reason": "refund"},
                ))]),
            )

    runner = StubRunner()
    session = MagicMock(state={})
    with patch.object(adk_bridge, "_get_or_create_session", new=AsyncMock(return_value=session)), \
         patch.object(adk_bridge, "_primary_runner", runner), \
         patch.object(adk_bridge, "_fallback_runner", runner), \
         patch.object(adk_bridge._session_service, "get_session", new=AsyncMock(return_value=session)):
        result = asyncio.run(adk_bridge.run_support_workflow("u", "f2-clean-after-action", "refund"))

    assert result["success"] is False
    assert result["error_type"] == "partial_after_action"
    assert calls == 1
