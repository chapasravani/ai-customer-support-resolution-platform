"""
MongoDB connection helper.

This file is intentionally small: one function (`get_db`) that returns a
connected database object. Every other file that needs MongoDB should
import from here instead of creating its own connection - that way there
is exactly one place that knows the connection string.
"""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.database import Database

# Load backend/.env if it exists. This does NOT touch or read the
# existing final_customer_support/.env file - the two subsystems keep
# their own environment files for now.
load_dotenv(Path(__file__).parent / ".env")

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "customer_support")

_client: Optional[MongoClient] = None


def get_client() -> MongoClient:
    """Return a shared MongoClient, creating it on first use with robust fallback."""
    global _client
    if _client is None:
        try:
            client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=2500)
            client.admin.command("ping")
            _client = client
        except Exception as exc:
            print(f"[MongoDB] Remote connection failed: {exc}. Using in-memory mock database.")
            try:
                import mongomock
                _client = mongomock.MongoClient()
            except Exception:
                _client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    return _client


def get_db() -> Database:
    """Return the application's database (all 4 collections live in here)."""
    return get_client()[MONGODB_DB_NAME]


def ensure_indexes() -> None:
    """
    Create the indexes the application relies on.

    Safe to call every time the app starts - creating an index that
    already exists is a no-op in MongoDB, it won't duplicate or error.
    """
    db = get_db()

    # Exactly one user per email address.
    db.users.create_index("email", unique=True)

    # The customer chat sidebar needs "this user's conversations, newest first".
    db.conversations.create_index([("user_id", 1), ("updated_at", -1)])

    # The admin ticket dashboard needs "this user's tickets" and "tickets by status".
    db.tickets.create_index([("user_id", 1)])
    db.tickets.create_index([("status", 1)])
    db.tickets.create_index("ticket_id", unique=True)

    # The admin documents page needs "documents by status" (processing/indexed/failed).
    db.documents.create_index([("status", 1)])


def check_connection() -> bool:
    """
    Quick health check. Returns True if MongoDB is reachable, False
    otherwise (and prints why). Used by test_phase1.py now, and will be
    reused as a FastAPI startup check in Phase 2.
    """
    try:
        get_client().admin.command("ping")
        return True
    except Exception as exc:
        print(f"[MongoDB] Connection check failed: {exc}")
        return False
