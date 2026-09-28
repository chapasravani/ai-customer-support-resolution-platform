"""
Phase 5 verification test suite — High Priority Reliability (H1–H6).

How to run:
    py -3.12 -m backend.test_phase5_reliability

What it tests:
    1. H1 — Duplicate support tickets per conversation:
       Subsequent escalations in the same conversation update the existing ticket
       rather than creating duplicate tickets.
    2. H2 — RAG document/chunk ID collisions:
       Chunk IDs combine source stem, index, and content hash, avoiding collisions
       even when filenames/stems match.
    3. H3 — RAG import and startup resilience:
       Importing retriever/context and querying without GOOGLE_API_KEY does not
       crash the application at startup or during queries.
    4. H4 — False ticket-created response:
       If ticket creation fails, the customer response and stored message accurately
       notify the user of the issue rather than falsely claiming success.
    5. H5 — Workflow failure responses not stored as valid assistant turns:
       When a workflow error occurs, it is not permanently logged to MongoDB as a
       successful assistant response.
    6. H6 — Conversation continuity across backend restarts:
       When the in-memory session service is cleared (simulating server restart),
       prior turns from MongoDB are re-hydrated into the session events.
"""

import asyncio
import os
from unittest.mock import patch, MagicMock

from backend import db, models
from backend.rag import retriever, context
from backend import adk_bridge
from backend.routes import chat
from backend.api_schemas import ChatMessageRequest


def test_h1_duplicate_support_tickets():
    print("Testing H1 — Duplicate support tickets per conversation...")
    # Create test user and conversation
    user = models.create_user("h1.test@example.com", "hash", "H1 Test", "customer")
    user_id = str(user["_id"])
    convo = models.create_conversation(user_id)
    convo_id = str(convo["_id"])

    try:
        # Simulate escalation 1
        escalation1 = {"should_escalate": True, "reason": "Order delayed"}
        with patch("backend.routes.chat.run_support_workflow", return_value={
            "response": "Your case has been forwarded to human support.",
            "success": True,
            "escalation": escalation1,
            "investigation": {},
            "resolution": {},
            "order_id": "ORD123",
            "issue_type": "delivery_issue",
        }):
            res1 = asyncio.run(chat.send_message(
                ChatMessageRequest(conversation_id=convo_id, message="My order is delayed"),
                user=user,
            ))

        ticket1 = models.get_ticket_for_conversation(convo_id)
        assert ticket1 is not None, "Expected ticket to be created for conversation"
        first_ticket_id = ticket1["ticket_id"]

        # Simulate escalation 2 in the SAME conversation
        escalation2 = {"should_escalate": True, "reason": "Still delayed after 3 days"}
        with patch("backend.routes.chat.run_support_workflow", return_value={
            "response": "I see you already have a case, checking on it.",
            "success": True,
            "escalation": escalation2,
            "investigation": {},
            "resolution": {},
            "order_id": "ORD123",
            "issue_type": "delivery_issue",
        }):
            res2 = asyncio.run(chat.send_message(
                ChatMessageRequest(conversation_id=convo_id, message="Any update on my order?"),
                user=user,
            ))

        ticket2 = models.get_ticket_for_conversation(convo_id)
        assert ticket2 is not None
        assert ticket2["ticket_id"] == first_ticket_id, f"Ticket ID changed: {ticket2['ticket_id']} != {first_ticket_id}"

        # Verify only 1 ticket exists for this user/conversation in MongoDB
        user_tickets = models.list_tickets(user_id=user_id)
        assert len(user_tickets) == 1, f"Expected 1 ticket for user, found {len(user_tickets)}"
        assert user_tickets[0]["issue"] == "Still delayed after 3 days", "Expected issue to be updated"
        print("  OK - single ticket maintained and updated per conversation.")
    finally:
        # Cleanup
        conn = db.get_db()
        conn.users.delete_one({"_id": user["_id"]})
        conn.conversations.delete_one({"_id": convo["_id"]})
        conn.tickets.delete_many({"user_id": user["_id"]})


def test_h2_rag_chunk_id_collision_prevention():
    print("Testing H2 — RAG document/chunk ID collision prevention...")
    chunks1 = ["Refunds are available within 30 days.", "Replacements require approval."]
    chunks2 = ["Refunds are available within 60 days.", "Different content with same filename."]

    # Both documents have the same stem "policy.txt" and "policy.pdf"
    with patch.object(retriever, "embed_documents", return_value=[[0.1] * 768, [0.2] * 768]):
        mock_col = MagicMock()
        with patch.object(retriever, "get_chroma_collection", return_value=mock_col):
            retriever.add_document_chunks(chunks1, source="docs/policy.txt")
            args1, kwargs1 = mock_col.upsert.call_args
            ids1 = kwargs1["ids"]

            retriever.add_document_chunks(chunks2, source="other_docs/policy.pdf")
            args2, kwargs2 = mock_col.upsert.call_args
            ids2 = kwargs2["ids"]

            # IDs must be different because of content hash and source difference
            assert ids1 != ids2, f"Collision detected between ids1 and ids2: {ids1} vs {ids2}"
            assert len(ids1) == 2 and len(ids2) == 2
            # Verify ID structure: stem_index_hash
            assert ids1[0].startswith("policy_0_")
            assert ids1[1].startswith("policy_1_")
            print("  OK - collision-resistant IDs verified with content hashes.")


def test_h3_rag_lazy_initialization():
    print("Testing H3 — RAG safe lazy initialization...")
    # Clear client and temporarily unset API key
    orig_key = os.environ.get("GOOGLE_API_KEY")
    orig_client = retriever._gemini_client
    try:
        if "GOOGLE_API_KEY" in os.environ:
            del os.environ["GOOGLE_API_KEY"]
        if "API_KEY" in os.environ:
            del os.environ["API_KEY"]
        retriever._gemini_client = None

        # search_documents must handle missing key gracefully and return []
        results = retriever.search_documents("what is the refund policy?")
        assert results == [], f"Expected empty list, got {results}"

        # context.retrieve_support_context must return default message without crashing
        ctx = context.retrieve_support_context("what is the refund policy?")
        assert "No relevant support-policy information was found." in ctx
        print("  OK - missing API key handled gracefully without crashing at import or query.")
    finally:
        if orig_key:
            os.environ["GOOGLE_API_KEY"] = orig_key
        retriever._gemini_client = orig_client


def test_h4_false_ticket_created_response():
    print("Testing H4 — False ticket-created response prevention...")
    user = models.create_user("h4.test@example.com", "hash", "H4 Test", "customer")
    user_id = str(user["_id"])
    convo = models.create_conversation(user_id)
    convo_id = str(convo["_id"])

    try:
        escalation = {"should_escalate": True, "reason": "System error requiring human"}
        with patch("backend.routes.chat.run_support_workflow", return_value={
            "response": "I have created ticket CASE-12345678 for you.",
            "success": True,
            "escalation": escalation,
            "investigation": {},
            "resolution": {},
            "order_id": "",
            "issue_type": "general_support",
        }):
            # Simulate create_ticket throwing a database failure
            with patch("backend.models.create_ticket", side_effect=RuntimeError("Database write error")):
                res = asyncio.run(chat.send_message(
                    ChatMessageRequest(conversation_id=convo_id, message="Help me please"),
                    user=user,
                ))

                # Verify customer response does NOT falsely claim ticket was created
                assert "CASE-12345678" not in res["response"], f"False ticket ID returned: {res['response']}"
                assert "encountered an issue" in res["response"] or "unable" in res["response"]

                # Verify MongoDB stored message also reflects the accurate response
                saved_convo = models.get_conversation(convo_id)
                assistant_msgs = [m for m in saved_convo["messages"] if m["role"] == "assistant"]
                assert len(assistant_msgs) == 1
                assert "CASE-12345678" not in assistant_msgs[0]["content"]

        print("  OK - customer is not falsely told a ticket was created when creation fails.")
    finally:
        conn = db.get_db()
        conn.users.delete_one({"_id": user["_id"]})
        conn.conversations.delete_one({"_id": convo["_id"]})


def test_h5_workflow_failure_not_saved_as_assistant_turn():
    print("Testing H5 — Workflow failures not saved as assistant response...")
    user = models.create_user("h5.test@example.com", "hash", "H5 Test", "customer")
    user_id = str(user["_id"])
    convo = models.create_conversation(user_id)
    convo_id = str(convo["_id"])

    try:
        with patch("backend.routes.chat.run_support_workflow", return_value={
            "response": "I'm temporarily receiving a high volume of requests.",
            "success": False,
            "error_type": "rate_limit",
            "escalation": {},
            "investigation": {},
            "resolution": {},
            "order_id": "",
            "issue_type": "",
        }):
            res = asyncio.run(chat.send_message(
                ChatMessageRequest(conversation_id=convo_id, message="Crash test"),
                user=user,
            ))

            assert res.get("error") == "rate_limit"

            # Verify NO assistant message was added to MongoDB for the failed workflow
            saved_convo = models.get_conversation(convo_id)
            assistant_msgs = [m for m in saved_convo["messages"] if m["role"] == "assistant"]
            assert len(assistant_msgs) == 0, f"Failed turn was incorrectly stored in MongoDB: {assistant_msgs}"

        print("  OK - failed workflow turns are not stored in conversation history.")
    finally:
        conn = db.get_db()
        conn.users.delete_one({"_id": user["_id"]})
        conn.conversations.delete_one({"_id": convo["_id"]})


def test_h6_session_continuity_across_restarts():
    print("Testing H6 — Session continuity across backend restarts...")
    user = models.create_user("h6.test@example.com", "hash", "H6 Test", "customer")
    user_id = str(user["_id"])
    convo = models.create_conversation(user_id)
    convo_id = str(convo["_id"])

    try:
        # Add historical turns to MongoDB
        models.add_message(convo_id, "user", "My laptop order ORD123 is delayed")
        models.add_message(convo_id, "assistant", "I see ORD123 is delayed by FastShip.")
        models.add_message(convo_id, "user", "Can I get a refund?")

        # Simulate backend restart by creating a fresh in-memory session service
        from google.adk.sessions import InMemorySessionService
        adk_bridge._session_service = InMemorySessionService()

        # Get or create session for convo_id
        session = asyncio.run(adk_bridge._get_or_create_session(user_id, convo_id))
        assert session is not None

        # Verify prior turns (turn 1 user + assistant) were re-hydrated into session.events
        assert len(session.events) >= 2, f"Expected at least 2 events rehydrated, got {len(session.events)}"
        event_texts = [
            "".join(p.text for p in e.content.parts)
            for e in session.events if e.content and e.content.parts
        ]
        assert any("ORD123 is delayed" in t for t in event_texts), f"Turn 1 user missing in {event_texts}"
        assert any("FastShip" in t for t in event_texts), f"Turn 1 assistant missing in {event_texts}"

        print("  OK - prior conversation turns successfully re-hydrated across restart.")
    finally:
        conn = db.get_db()
        conn.users.delete_one({"_id": user["_id"]})
        conn.conversations.delete_one({"_id": convo["_id"]})


def main():
    print("==================================================")
    print("PHASE 5 VERIFICATION SUITE — HIGH PRIORITY RELIABILITY")
    print("==================================================")
    test_h1_duplicate_support_tickets()
    test_h2_rag_chunk_id_collision_prevention()
    test_h3_rag_lazy_initialization()
    test_h4_false_ticket_created_response()
    test_h5_workflow_failure_not_saved_as_assistant_turn()
    test_h6_session_continuity_across_restarts()
    print("\nALL PHASE 5 CHECKS PASSED.")


if __name__ == "__main__":
    main()
