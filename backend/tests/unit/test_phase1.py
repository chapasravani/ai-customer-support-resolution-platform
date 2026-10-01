"""
Phase 1 sanity check - run this manually to confirm MongoDB is wired up
correctly, BEFORE anything else (FastAPI, ADK) touches it.

How to run:
    1. Make sure MongoDB is running (local `mongod`, or a MongoDB Atlas
       connection string set as MONGODB_URI in the root .env).
    2. From the project root:  python -m backend.test_phase1

What it does:
    - Checks the connection
    - Creates the indexes
    - Creates one test user, conversation, ticket, and document
    - Reads each one back and checks the values match
    - Deletes everything it created, so you can run this again anytime
      without leaving test data behind
"""

from backend.app.infrastructure import db
from backend.app.domains import models


def main() -> None:
    print("1. Checking database connection...")
    info = db.get_storage_info()
    if not (info.get("mongodb_connected") or info.get("persistent_fallback_active")):
        print("   FAILED - is MongoDB running? Is MONGODB_URI correct?")
        return
    if info.get("persistent_fallback_active"):
        print("   OK - operating with local persistent fallback storage.")
    else:
        print("   OK - connected to MongoDB.")

    print("2. Creating indexes...")
    db.ensure_indexes()
    print("   OK.")

    created_ids = {"users": [], "conversations": [], "tickets": [], "documents": []}

    try:
        # --- USERS ---
        print("3. Creating a test user...")
        user = models.create_user(
            email="phase1.test@example.com",
            hashed_password="not-a-real-hash",
            name="Phase 1 Test User",
            role="customer",
        )
        created_ids["users"].append(user["_id"])
        fetched = models.get_user_by_email("phase1.test@example.com")
        assert fetched is not None and fetched["name"] == "Phase 1 Test User"
        print(f"   OK - user created and fetched back (id={user['_id']}).")

        # --- CONVERSATIONS ---
        print("4. Creating a conversation and adding messages...")
        convo = models.create_conversation(str(user["_id"]))
        created_ids["conversations"].append(convo["_id"])
        models.add_message(str(convo["_id"]), "user", "My order is delayed, what should I do?")
        models.add_message(str(convo["_id"]), "assistant", "I checked your order and it qualifies for...")
        fetched_convo = models.get_conversation(str(convo["_id"]))
        assert fetched_convo is not None and len(fetched_convo["messages"]) == 2
        print(f"   OK - conversation has {len(fetched_convo['messages'])} messages.")

        listed = models.list_conversations_for_user(str(user["_id"]))
        assert len(listed) >= 1
        print(f"   OK - list_conversations_for_user returned {len(listed)} conversation(s).")

        # --- TICKETS ---
        print("5. Creating a ticket and updating its status...")
        ticket = models.create_ticket(
            ticket_id="TEST-CASE-0001",
            user_id=str(user["_id"]),
            issue="Delayed order",
            order_id="ORD123",
            conversation_id=str(convo["_id"]),
            priority="medium",
            source_reference="CASE-20260922-TEST01",
        )
        created_ids["tickets"].append(ticket["_id"])
        updated = models.update_ticket_status("TEST-CASE-0001", "resolved", "Refund issued.")
        assert updated is True
        fetched_ticket = models.get_ticket("TEST-CASE-0001")
        assert fetched_ticket["status"] == "resolved"
        print(f"   OK - ticket created and status updated to '{fetched_ticket['status']}'.")

        # --- DOCUMENTS ---
        print("6. Creating a document record and marking it indexed...")
        doc = models.create_document_record("refund-policy-v3.pdf", str(user["_id"]))
        created_ids["documents"].append(doc["_id"])
        models.update_document_status(str(doc["_id"]), "indexed", chunk_count=12, vector_ids=["v1", "v2"])
        fetched_doc = models.get_document(str(doc["_id"]))
        assert fetched_doc["status"] == "indexed" and fetched_doc["chunk_count"] == 12
        print(f"   OK - document status is '{fetched_doc['status']}' with {fetched_doc['chunk_count']} chunks.")

        print("\nALL PHASE 1 CHECKS PASSED.")

    finally:
        # Clean up so this script is safe to re-run.
        print("\n7. Cleaning up test data...")
        conn = db.get_db()
        for _id in created_ids["users"]:
            conn.users.delete_one({"_id": _id})
        for _id in created_ids["conversations"]:
            conn.conversations.delete_one({"_id": _id})
        for _id in created_ids["tickets"]:
            conn.tickets.delete_one({"_id": _id})
        for _id in created_ids["documents"]:
            conn.documents.delete_one({"_id": _id})
        print("   Done - test data removed.")


if __name__ == "__main__":
    main()
