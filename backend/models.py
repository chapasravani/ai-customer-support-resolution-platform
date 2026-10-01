"""
Thin data-access helpers for the four MongoDB collections:
users, conversations, tickets, documents.

Design rule for this file: each function does ONE thing (create/read/
update) for ONE collection, and nothing here talks to FastAPI, auth, or
ADK. Keeping this file "just MongoDB" makes it easy to test on its own
(see test_phase1.py) and easy to reuse once the FastAPI routes and the
ADK bridge are built in later phases.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from bson import ObjectId
from bson.errors import InvalidId

from .db import get_db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _oid(id_str: str) -> Optional[ObjectId]:
    """Safely convert a string id to ObjectId. Returns None if it's not a valid id."""
    try:
        return ObjectId(id_str)
    except (InvalidId, TypeError):
        return None


# ---------------------------------------------------------------------------
# USERS
# ---------------------------------------------------------------------------

def create_user(email: str, hashed_password: str, name: str, role: str = "customer", customer_id: str = "") -> dict:
    """
    Insert a new user document.

    `hashed_password` must already be hashed before it gets here - this
    file never hashes or verifies passwords itself. That logic belongs
    in the Phase 2 auth module, which is the only thing that should
    import a hashing library.
    """
    clean_email = email.lower().strip()
    doc = {
        "email": clean_email,
        "hashed_password": hashed_password,
        "name": name,
        "role": role,
        "created_at": _now(),
    }
    if customer_id:
        doc["customer_id"] = customer_id

    result = get_db().users.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def get_customer_id_for_user(user: dict) -> str:
    """
    Return the customer_id associated with a user.
    Uses existing explicit customer_id if set, or generates a consistent,
    collision-resistant customer ID based on the complete user _id (N4).
    Never links automatically via unverified email (N1).
    """
    if not user:
        return ""
    if user.get("customer_id"):
        return user["customer_id"]

    user_id = user.get("_id")
    user_id_str = str(user_id or "unknown")
    cid = f"C_{user_id_str}"
    if user_id:
        try:
            get_db().users.update_one({"_id": user_id}, {"$set": {"customer_id": cid}})
            user["customer_id"] = cid
        except Exception:
            pass
    return cid


def get_user_by_email(email: str) -> Optional[dict]:
    return get_db().users.find_one({"email": email.lower().strip()})


def get_user_by_id(user_id: str) -> Optional[dict]:
    oid = _oid(user_id)
    if not oid:
        return None
    return get_db().users.find_one({"_id": oid})


def update_user_password(email: str, hashed_password: str) -> bool:
    """Update stored password hash for an existing user."""
    result = get_db().users.update_one(
        {"email": email.lower().strip()},
        {"$set": {"hashed_password": hashed_password}}
    )
    return result.modified_count > 0


def update_user_role(email: str, role: str) -> bool:
    """Update role for an existing user (e.g. 'admin' or 'customer')."""
    result = get_db().users.update_one(
        {"email": email.lower().strip()},
        {"$set": {"role": role.lower().strip()}}
    )
    return result.modified_count > 0


def list_admin_users() -> list[dict]:
    """List all accounts with admin role."""
    return list(get_db().users.find({"role": "admin"}, {"hashed_password": 0}))


# ---------------------------------------------------------------------------
# CONVERSATIONS
# ---------------------------------------------------------------------------

def create_conversation(user_id: str) -> dict:
    """Start a new, empty conversation for a user."""
    doc = {
        "user_id": _oid(user_id) or user_id,
        "status": "active",
        "title": "New conversation",
        "messages": [],
        "message_count": 0,
        "started_at": _now(),
        "updated_at": _now(),
    }
    result = get_db().conversations.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def add_message(conversation_id: str, role: str, content: str, request_id: str = "") -> Optional[dict]:
    """
    Append one message (role is 'user' or 'assistant') to an existing
    conversation and bump its updated_at timestamp so it moves to the
    top of the sidebar's "most recent" sort.
    """
    oid = _oid(conversation_id)
    if not oid:
        return None

    message = {"id": uuid4().hex, "role": role, "content": content, "timestamp": _now()}
    if request_id:
        message["request_id"] = request_id

    update = {
        "$push": {"messages": message},
        "$inc": {"message_count": 1},
        "$set": {"updated_at": _now()},
    }

    # Give a new conversation a useful automatic title based on the
    # customer's first message. Explicitly renamed conversations are
    # preserved because their title is no longer "New conversation".
    if role == "user":
        existing = get_db().conversations.find_one(
            {"_id": oid},
            {"title": 1, "messages": 1},
        )
        if existing and existing.get("title") in (None, "", "New conversation"):
            clean_title = " ".join(content.split()).strip()
            if clean_title:
                update["$set"]["title"] = (
                    clean_title[:77] + "..."
                    if len(clean_title) > 80
                    else clean_title
                )

    get_db().conversations.update_one(
        {"_id": oid},
        update,
    )
    return message


def set_message_failed(conversation_id: str, message_id: str, failed: bool) -> bool:
    oid = _oid(conversation_id)
    if not oid:
        return False
    result = get_db().conversations.update_one(
        {"_id": oid, "messages.id": message_id},
        {"$set": {"messages.$.failed": failed}},
    )
    return result.matched_count > 0


def claim_chat_request(user_id: str, request_id: str, conversation_id: str = "") -> tuple[str, dict]:
    """Atomically claim an idempotency key scoped to its authenticated user."""
    from pymongo.errors import DuplicateKeyError
    from pymongo import ReturnDocument

    collection = get_db().chat_requests
    collection.create_index([("user_id", 1), ("request_id", 1)], unique=True)
    record = {
        "user_id": _oid(user_id) or user_id,
        "request_id": request_id,
        "conversation_id": conversation_id,
        "status": "in_progress",
        "response": "",
        "created_at": _now(),
    }
    try:
        result = collection.insert_one(record)
        record["_id"] = result.inserted_id
        return "claimed", record
    except DuplicateKeyError:
        key = {"user_id": record["user_id"], "request_id": request_id}
        existing = collection.find_one(key)
        if existing.get("status") == "done":
            return "done", existing
        if existing.get("status") == "in_progress":
            created_at = existing.get("created_at")
            comparable_created_at = created_at
            if isinstance(comparable_created_at, datetime) and comparable_created_at.tzinfo is None:
                comparable_created_at = comparable_created_at.replace(tzinfo=timezone.utc)
            if not isinstance(comparable_created_at, datetime) or comparable_created_at >= _now() - timedelta(minutes=5):
                return "in_progress", existing
            stale = collection.find_one_and_update(
                {**key, "status": "in_progress", "created_at": created_at},
                {"$set": {"status": "failed"}},
                return_document=ReturnDocument.AFTER,
            )
            if not stale:
                return "in_progress", collection.find_one(key)
        retried = collection.find_one_and_update(
            {**key, "status": "failed"},
            {"$set": {"status": "in_progress"}},
            return_document=ReturnDocument.AFTER,
        )
        if retried:
            return "retry", retried
        return "in_progress", collection.find_one(key)


def update_chat_request(user_id: str, request_id: str, status: str, response: str = "", conversation_id: str = "") -> bool:
    key = {"user_id": _oid(user_id) or user_id, "request_id": request_id}
    update = {"status": status}
    if response:
        update["response"] = response
    if conversation_id:
        update["conversation_id"] = conversation_id
    result = get_db().chat_requests.update_one(key, {"$set": update})
    return result.matched_count > 0


def rename_conversation(conversation_id: str, title: str) -> bool:
    oid = _oid(conversation_id)
    if not oid:
        return False

    clean_title = " ".join(title.split()).strip()
    if not clean_title:
        return False

    result = get_db().conversations.update_one(
        {"_id": oid},
        {"$set": {"title": clean_title[:80], "updated_at": _now()}},
    )
    return result.modified_count > 0


def delete_conversation(conversation_id: str) -> bool:
    oid = _oid(conversation_id)
    if not oid:
        return False

    result = get_db().conversations.delete_one({"_id": oid})
    return result.deleted_count > 0


def get_conversation(conversation_id: str) -> Optional[dict]:
    oid = _oid(conversation_id)
    if not oid:
        return None
    return get_db().conversations.find_one({"_id": oid})


def list_conversations_for_user(
    user_id: str,
    limit: int = 20,
    skip: int = 0,
    include_messages: bool = True,
) -> list[dict]:
    """Most recently updated conversations first - this is what the sidebar shows."""
    oid = _oid(user_id) or user_id
    projection = None if include_messages else {"messages": 0}
    cursor = (
        get_db()
        .conversations.find({"user_id": oid}, projection=projection)
        .sort("updated_at", -1)
        .skip(skip)
        .limit(limit)
    )
    convos = list(cursor)
    for c in convos:
        if "message_count" not in c:
            if "messages" in c:
                c["message_count"] = len(c["messages"])
            else:
                doc = get_db().conversations.find_one({"_id": c["_id"]}, {"messages": 1})
                c["message_count"] = len(doc.get("messages", [])) if doc else 0
    return convos


def save_feedback(
    conversation_id: str,
    user_id: str,
    rating: str,
    message_index: Optional[int] = None,
) -> bool:
    """Record customer satisfaction feedback for a conversation (L4)."""
    oid = _oid(conversation_id)
    if not oid:
        return False
    u_oid = _oid(user_id) or user_id
    convo = get_db().conversations.find_one({"_id": oid, "user_id": u_oid})
    if not convo:
        return False

    feedback_entry = {
        "rating": rating,
        "message_index": message_index,
        "recorded_at": _now(),
    }
    result = get_db().conversations.update_one(
        {"_id": oid, "user_id": u_oid},
        {"$push": {"feedback": feedback_entry}, "$set": {"updated_at": _now()}},
    )
    return result.matched_count > 0


# ---------------------------------------------------------------------------
# TICKETS
# ---------------------------------------------------------------------------

def create_ticket(
    ticket_id: str,
    user_id: str,
    issue: str,
    order_id: str = "",
    conversation_id: str = "",
    priority: str = "medium",
    status: str = "open",
    source_reference: str = "",
) -> dict:
    """
    `ticket_id` is a human-friendly identifier. In later phases this will
    usually be the same reference tools/business_actions.py already
    generates today (e.g. "CASE-20260922-AB12CD"). MongoDB is the ticket
    system of record for API-created tickets; action records stay separate.
    """
    doc = {
        "ticket_id": ticket_id,
        "user_id": _oid(user_id) or user_id,
        "conversation_id": _oid(conversation_id) if conversation_id else None,
        "order_id": order_id,
        "issue": issue,
        "status": status,
        "priority": priority,
        "resolution_summary": "",
        "source_reference": source_reference,
        "created_at": _now(),
        "updated_at": _now(),
    }
    if doc["conversation_id"] and status in {"open", "in_progress"}:
        doc["active_ticket_key"] = str(doc["conversation_id"])
    result = get_db().tickets.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def get_ticket(ticket_id: str) -> Optional[dict]:
    """Look up by the human-friendly ticket_id (not the Mongo _id)."""
    return get_db().tickets.find_one({"ticket_id": ticket_id})


def update_ticket_status(ticket_id: str, status: str, resolution_summary: str = "") -> bool:
    ticket = get_ticket(ticket_id)
    if not ticket:
        return False
    update: dict[str, Any] = {"status": status, "updated_at": _now()}
    if resolution_summary:
        update["resolution_summary"] = resolution_summary
    conversation_id = ticket.get("conversation_id")
    if status in {"open", "in_progress"} and conversation_id:
        update["active_ticket_key"] = str(conversation_id)
        changes = {"$set": update}
    else:
        changes = {"$set": update, "$unset": {"active_ticket_key": ""}}
    result = get_db().tickets.update_one({"ticket_id": ticket_id}, changes)
    return result.matched_count > 0


def get_ticket_for_conversation(conversation_id: str) -> Optional[dict]:
    """Retrieve existing support ticket associated with a conversation (H1)."""
    oid = _oid(conversation_id)
    if not oid and not conversation_id:
        return None
    query = {"$or": [{"conversation_id": oid}, {"conversation_id": str(conversation_id)}]} if oid else {"conversation_id": str(conversation_id)}
    query["status"] = {"$in": ["open", "in_progress"]}
    return get_db().tickets.find_one(query, sort=[("created_at", -1)])


def find_or_create_open_ticket(
    ticket_id: str,
    user_id: str,
    issue: str,
    order_id: str,
    conversation_id: str,
    source_reference: str = "",
) -> dict:
    """Atomically reuse an active ticket or create the conversation's open ticket."""
    from pymongo import ReturnDocument

    oid = _oid(conversation_id)
    query = {"conversation_id": oid or conversation_id, "status": {"$in": ["open", "in_progress"]}}
    doc = {
        "ticket_id": ticket_id,
        "user_id": _oid(user_id) or user_id,
        "conversation_id": oid or conversation_id,
        "active_ticket_key": str(oid or conversation_id),
        "order_id": order_id,
        "issue": issue,
        "status": "open",
        "priority": "medium",
        "resolution_summary": "",
        "source_reference": source_reference,
        "created_at": _now(),
        "updated_at": _now(),
    }
    tickets = get_db().tickets
    try:
        return tickets.find_one_and_update(
            query,
            {"$setOnInsert": doc},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except Exception as exc:
        from pymongo.errors import DuplicateKeyError

        if not isinstance(exc, DuplicateKeyError):
            raise
        # A concurrent upsert may win the unique active-ticket key race.
        existing = tickets.find_one(query, sort=[("created_at", -1)])
        if existing:
            return existing
        raise


def update_ticket_issue(ticket_id: str, issue: str, order_id: str = "") -> bool:
    """Update issue/order on an existing ticket (H1)."""
    update: dict[str, Any] = {"issue": issue, "updated_at": _now()}
    if order_id:
        update["order_id"] = order_id
    result = get_db().tickets.update_one({"ticket_id": ticket_id}, {"$set": update})
    return result.matched_count > 0


def list_tickets(status: Optional[str] = None, user_id: Optional[str] = None, limit: int = 50) -> list[dict]:
    query: dict[str, Any] = {}
    if status:
        query["status"] = status
    if user_id:
        query["user_id"] = _oid(user_id) or user_id
    cursor = get_db().tickets.find(query).sort("created_at", -1).limit(limit)
    return list(cursor)


# ---------------------------------------------------------------------------
# DOCUMENTS
# ---------------------------------------------------------------------------

def create_document_record(filename: str, uploaded_by: str) -> dict:
    """Called the moment a file is uploaded, before processing/chunking starts."""
    doc = {
        "filename": filename,
        "uploaded_by": _oid(uploaded_by) or uploaded_by,
        "upload_date": _now(),
        "status": "processing",
        "chunk_count": 0,
        "vector_ids": [],
    }
    result = get_db().documents.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def update_document_status(
    document_id: str,
    status: str,
    chunk_count: int = 0,
    vector_ids: Optional[list[str]] = None,
) -> bool:
    oid = _oid(document_id)
    if not oid:
        return False
    update: dict[str, Any] = {"status": status}
    if chunk_count:
        update["chunk_count"] = chunk_count
    if vector_ids is not None:
        update["vector_ids"] = vector_ids
    result = get_db().documents.update_one({"_id": oid}, {"$set": update})
    return result.modified_count > 0


def list_documents(limit: int = 50) -> list[dict]:
    cursor = get_db().documents.find().sort("upload_date", -1).limit(limit)
    return list(cursor)


def get_document(document_id: str) -> Optional[dict]:
    oid = _oid(document_id)
    if not oid:
        return None
    return get_db().documents.find_one({"_id": oid})


def delete_document(document_id: str) -> bool:
    oid = _oid(document_id)
    if not oid:
        return False
    result = get_db().documents.delete_one({"_id": oid})
    return result.deleted_count > 0
