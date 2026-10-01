"""
MongoDB connection helper.

This file is intentionally small: one function (`get_db`) that returns a
connected database object. Every other file that needs MongoDB should
import from here instead of creating its own connection - that way there
is exactly one place that knows the connection string.
"""

import os
import tempfile
import threading
from pathlib import Path
from typing import Any
from bson import json_util
from dotenv import load_dotenv
from pymongo import MongoClient

# Load backend/.env if it exists. override=False ensures deployment/CI
# environment variables take precedence over local .env files (N7).
load_dotenv(Path(__file__).parent / ".env", override=False)

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017").strip().strip("\"'")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "customer_support").strip().strip("\"'")

_APP_COLLECTIONS = ["users", "conversations", "tickets", "documents", "chat_requests"]

def get_data_file() -> Path:
    custom = os.getenv("SUPPORTAI_DATA_FILE")
    if custom:
        p = Path(custom)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    default_p = Path(__file__).parent / "data" / "runtime" / "db_store.json"
    default_p.parent.mkdir(parents=True, exist_ok=True)
    return default_p


DATA_FILE = get_data_file()

# Thread-safe reentrant lock protecting local fallback reads, writes, and syncs
# NOTE (N8): This lock coordinates threads within a single Python process.
# In-process mongomock does not provide cross-process coordination across independent
# CLI utilities and API workers. For multi-process or production deployments, configure
# real MongoDB via MONGODB_URI.
_db_lock = threading.RLock()


def _ensure_indexes_on_db(target_db) -> None:
    """Helper to recreate application indexes directly on a database instance."""
    # Exactly one user per email address.
    target_db.users.create_index("email", unique=True)

    # The customer chat sidebar needs "this user's conversations, newest first".
    target_db.conversations.create_index([("user_id", 1), ("updated_at", -1)])

    # The admin ticket dashboard needs "this user's tickets" and "tickets by status".
    target_db.tickets.create_index([("user_id", 1)])
    target_db.tickets.create_index([("status", 1)])
    target_db.tickets.create_index("ticket_id", unique=True)
    target_db.tickets.create_index([("conversation_id", 1)])
    target_db.tickets.create_index("active_ticket_key", unique=True, sparse=True)

    # The admin documents page needs "documents by status" (processing/indexed/failed).
    target_db.documents.create_index([("status", 1)])

    target_db.chat_requests.create_index([("user_id", 1), ("request_id", 1)], unique=True)


class PersistentCollection:
    def __init__(self, raw_col, get_db_fn):
        self._col = raw_col
        self._get_db = get_db_fn

    def __getattr__(self, name):
        attr = getattr(self._col, name)
        if callable(attr):
            def wrapper(*args, **kwargs):
                with _db_lock:
                    self._get_db()._sync_from_disk()
                    res = attr(*args, **kwargs)
                    if name in (
                        "insert_one", "insert_many",
                        "update_one", "update_many",
                        "delete_one", "delete_many",
                        "replace_one", "find_one_and_update",
                        "find_one_and_delete"
                    ):
                        self._get_db()._sync_to_disk()
                    return res
            return wrapper
        return attr


class PersistentDatabase:
    def __init__(self, raw_db):
        self._db = raw_db
        self._last_mtime = 0
        self.name = getattr(raw_db, "name", "customer_support")
        with _db_lock:
            self._sync_from_disk()

    def _sync_from_disk(self):
        with _db_lock:
            data_file = get_data_file()
            if not data_file.exists():
                _ensure_indexes_on_db(self._db)
                return
            try:
                mtime = data_file.stat().st_mtime
                if mtime > self._last_mtime:
                    content = data_file.read_text(encoding="utf-8")
                    if content.strip():
                        try:
                            data = json_util.loads(content)
                        except Exception as parse_err:
                            # Do not silently continue after detecting corrupted persistent storage
                            raise RuntimeError(
                                f"Corrupted or unparseable persistent database file detected at '{data_file}': {parse_err}"
                            ) from parse_err

                        for col_name in _APP_COLLECTIONS:
                            self._db[col_name].drop()
                            docs = data.get(col_name, [])
                            if docs:
                                self._db[col_name].insert_many(docs)
                        # Re-create/ensure required indexes after reload
                        _ensure_indexes_on_db(self._db)
                    else:
                        _ensure_indexes_on_db(self._db)
                    self._last_mtime = mtime
            except RuntimeError:
                raise
            except Exception as exc:
                raise RuntimeError(f"Failed to sync persistent database from disk: {exc}") from exc

    def _sync_to_disk(self):
        with _db_lock:
            data_file = get_data_file()
            tmp_path = None
            try:
                data = {
                    col: list(self._db[col].find())
                    for col in _APP_COLLECTIONS
                }
                serialized = json_util.dumps(data, indent=2)

                # Atomic write using temporary file in same folder followed by atomic replace
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=data_file.parent,
                    prefix="db_store_tmp_",
                    suffix=".json",
                    delete=False,
                ) as tmp_file:
                    tmp_file.write(serialized)
                    tmp_file.flush()
                    os.fsync(tmp_file.fileno())
                    tmp_path = Path(tmp_file.name)

                os.replace(tmp_path, data_file)
                self._last_mtime = data_file.stat().st_mtime
            except Exception as exc:
                if tmp_path and tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except Exception:
                        pass
                raise RuntimeError(f"Failed to atomically persist database to disk: {exc}") from exc

    def __getitem__(self, name):
        return PersistentCollection(self._db[name], lambda: self)

    def __getattr__(self, name):
        if name in _APP_COLLECTIONS:
            return self[name]
        return getattr(self._db, name)


class PersistentClient:
    def __init__(self, raw_client):
        self._raw_client = raw_client
        self._databases = {}

    def __getitem__(self, name):
        if name not in self._databases:
            self._databases[name] = PersistentDatabase(self._raw_client[name])
        return self._databases[name]

    def __getattr__(self, name):
        if name == "admin":
            return self._raw_client.admin
        return getattr(self._raw_client, name)


_client = None
_using_mock = False


def is_using_mock() -> bool:
    """Return True if application is running on local persistent mock database."""
    global _using_mock
    return _using_mock


def set_local_mode() -> None:
    """Explicitly switch database client to local persistent fallback storage."""
    global _client, _using_mock
    import mongomock
    raw_mock = mongomock.MongoClient()
    _client = PersistentClient(raw_mock)
    _using_mock = True


def get_client() -> Any:
    """Return a shared MongoClient, creating it on first use with persistent fallback."""
    global _client, _using_mock
    if _client is None:
        try:
            client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=2500)
            client.admin.command("ping")
            _client = client
            _using_mock = False
        except Exception as exc:
            print(f"[MongoDB] Remote connection failed: {exc}. Using file-backed persistent local database.")
            try:
                import mongomock
                raw_mock = mongomock.MongoClient()
                _client = PersistentClient(raw_mock)
                _using_mock = True
            except Exception:
                _client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
                _using_mock = False
    return _client


def get_db() -> Any:
    """Return the application's database (all 4 collections live in here)."""
    return get_client()[MONGODB_DB_NAME]


def ensure_indexes() -> None:
    """
    Create the indexes the application relies on.

    Safe to call every time the app starts - creating an index that
    already exists is a no-op in MongoDB, it won't duplicate or error.
    """
    with _db_lock:
        db = get_db()
        _ensure_indexes_on_db(db)


def check_connection() -> bool:
    """
    Check if REAL MongoDB is reachable. Returns False if running on mock fallback
    or if the remote MongoDB connection fails.
    """
    global _client, _using_mock
    if _client is None:
        get_client()
    if _using_mock:
        return False
    try:
        _client.admin.command("ping")
        return True
    except Exception as exc:
        print(f"[MongoDB] Connection check failed: {exc}")
        return False


def get_storage_info() -> dict:
    """
    Return detailed health information clearly distinguishing real MongoDB
    from local persistent fallback storage.
    """
    global _using_mock
    if _client is None:
        get_client()

    if _using_mock:
        return {
            "status": "ok",
            "storage_type": "local_persistent_fallback",
            "mongodb_connected": False,
            "persistent_fallback_active": True,
            "details": "Using file-backed persistent local database (mongomock).",
        }

    connected = check_connection()
    return {
        "status": "ok" if connected else "degraded",
        "storage_type": "mongodb",
        "mongodb_connected": connected,
        "persistent_fallback_active": False,
        "details": "Connected to remote MongoDB." if connected else "Remote MongoDB unreachable.",
    }
