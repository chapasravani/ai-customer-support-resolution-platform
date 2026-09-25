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

from datetime import datetime, timezone
from typing import Any, Optional

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

def create_user(email: str, hashed_password: str, name: str, role: str = "customer") -> dict:
    """
    Insert a new user document.

    `hashed_password` must already be hashed before it gets here - this
    file never hashes or verifies passwords itself. That logic belongs
    in the Phase 2 auth module, which is the only thing that should
    import a hashing library.
    """
    doc = {
        "email": email.lower().strip(),
        "hashed_password": hashed_password,
        "name": name,
        "role": role,
        "created_at": _now(),
    }
    result = get_db().users.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


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
        "started_at": _now(),
        "updated_at": _now(),
    }
    result = get_db().conversations.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def add_message(conversation_id: str, role: str, content: str) -> Optional[dict]:
    """
    Append one message (role is 'user' or 'assistant') to an existing
    conversation and bump its updated_at timestamp so it moves to the
    top of the sidebar's "most recent" sort.
    """
    oid = _oid(conversation_id)
    if not oid:
        return None

    message = {"role": role, "content": content, "timestamp": _now()}

    update = {
        "$push": {"messages": message},
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


def list_conversations_for_user(user_id: str, limit: int = 20) -> list[dict]:
    """Most recently updated conversations first - this is what the sidebar shows."""
    oid = _oid(user_id) or user_id
    cursor = (
        get_db()
        .conversations.find({"user_id": oid})
        .sort("updated_at", -1)
        .limit(limit)
    )
    return list(cursor)


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
    generates today (e.g. "CASE-20260922-AB12CD"), so a Mongo ticket and
    the existing JSON-based action log stay traceable to the same event.
    See Decision B in IMPLEMENTATION_PROGRESS.md for why it works this way.
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
    result = get_db().tickets.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def get_ticket(ticket_id: str) -> Optional[dict]:
    """Look up by the human-friendly ticket_id (not the Mongo _id)."""
    return get_db().tickets.find_one({"ticket_id": ticket_id})


def update_ticket_status(ticket_id: str, status: str, resolution_summary: str = "") -> bool:
    update: dict[str, Any] = {"status": status, "updated_at": _now()}
    if resolution_summary:
        update["resolution_summary"] = resolution_summary
    result = get_db().tickets.update_one({"ticket_id": ticket_id}, {"$set": update})
    return result.modified_count > 0


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
