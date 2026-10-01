import asyncio
import pytest
from fastapi import HTTPException

from backend.rag import context, retriever
from backend import main
from backend.routes import documents


def test_rag_outage_is_distinct_from_empty_collection(monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("Chroma unavailable")

    monkeypatch.setattr(retriever, "get_chroma_collection", unavailable)
    with pytest.raises(RuntimeError, match="Chroma unavailable"):
        retriever.search_documents("return policy")
    monkeypatch.setattr(context, "search_documents", unavailable)
    assert context.retrieve_support_context("return policy").startswith("RAG_UNAVAILABLE:")
    assert retriever.collection_count() is None

    monkeypatch.setattr(context, "search_documents", lambda **kwargs: [])
    assert context.retrieve_support_context("return policy") == (
        "No relevant support-policy information was found."
    )


def test_health_reports_rag_outage(monkeypatch):
    monkeypatch.setattr(main.db, "get_storage_info", lambda: {
        "status": "ok",
        "storage_type": "mongodb",
        "mongodb_connected": True,
        "persistent_fallback_active": False,
    })
    monkeypatch.setattr(main, "collection_count", lambda: None)
    assert main.health()["rag"] == "unavailable"


class _Upload:
    filename = "policy.txt"

    async def read(self):
        return b"policy text"


def _doc(doc_id, filename="policy.txt", vector_ids=None, status="indexed"):
    return {
        "_id": doc_id,
        "filename": filename,
        "status": status,
        "chunk_count": len(vector_ids or []),
        "vector_ids": vector_ids or [],
        "upload_date": "today",
    }


def test_replace_indexes_new_version_then_supersedes_old(monkeypatch, tmp_path):
    old = _doc("old-id", vector_ids=[f"old-id:{i}" for i in range(5)])
    new = _doc("new-id", status="processing")
    records = {"old-id": old, "new-id": new}
    deleted = []

    monkeypatch.setattr(documents, "prepare_document", lambda path: ["new-1", "new-2"])
    monkeypatch.setattr(documents.models, "create_document_record", lambda **kwargs: new)
    monkeypatch.setattr(documents, "add_document_chunks", lambda **kwargs: ["new-id:0", "new-id:1"])
    monkeypatch.setattr(documents, "delete_document_chunks", lambda **kwargs: deleted.extend(kwargs["vector_ids"]) or len(kwargs["vector_ids"]))

    def update(document_id, status, chunk_count=0, vector_ids=None):
        records[document_id]["status"] = status
        if vector_ids is not None:
            records[document_id]["vector_ids"] = vector_ids
            records[document_id]["chunk_count"] = chunk_count
        return True

    monkeypatch.setattr(documents.models, "update_document_status", update)
    monkeypatch.setattr(documents.models, "get_document", lambda document_id: records[document_id])

    result = asyncio.run(documents.upload_document(_Upload(), {"_id": "admin"}, replace_document_id="old-id"))

    assert result["id"] == "new-id"
    assert records["new-id"]["vector_ids"] == ["new-id:0", "new-id:1"]
    assert deleted == old["vector_ids"]
    assert records["old-id"]["status"] == "superseded"


def test_index_status_failure_rolls_back_new_chunks(monkeypatch):
    new = _doc("new-id", status="processing")
    deleted = []
    statuses = []

    monkeypatch.setattr(documents, "prepare_document", lambda path: ["chunk"])
    monkeypatch.setattr(documents.models, "create_document_record", lambda **kwargs: new)
    monkeypatch.setattr(documents, "add_document_chunks", lambda **kwargs: ["new-id:0"])
    monkeypatch.setattr(documents, "delete_document_chunks", lambda **kwargs: deleted.extend(kwargs["vector_ids"]) or 1)

    def update(document_id, status, chunk_count=0, vector_ids=None):
        statuses.append(status)
        if status == "indexed":
            raise RuntimeError("Mongo update failed")
        return True

    monkeypatch.setattr(documents.models, "update_document_status", update)
    with pytest.raises(HTTPException) as error:
        asyncio.run(documents.upload_document(_Upload(), {"_id": "admin"}, replace_document_id=None))

    assert error.value.status_code == 500
    assert deleted == ["new-id:0"]
    assert "failed" in statuses


def test_partial_chroma_write_is_rolled_back(monkeypatch):
    new = _doc("new-id", status="processing")
    deleted = []
    monkeypatch.setattr(documents, "prepare_document", lambda path: ["chunk"])
    monkeypatch.setattr(documents.models, "create_document_record", lambda **kwargs: new)

    def add_then_fail(**kwargs):
        raise RuntimeError("Chroma failed after a partial write")

    monkeypatch.setattr(documents, "add_document_chunks", add_then_fail)
    monkeypatch.setattr(documents, "delete_document_chunks", lambda **kwargs: deleted.extend(kwargs["vector_ids"]) or 1)
    monkeypatch.setattr(documents.models, "update_document_status", lambda **kwargs: True)

    with pytest.raises(HTTPException) as error:
        asyncio.run(documents.upload_document(_Upload(), {"_id": "admin"}, replace_document_id=None))

    assert error.value.status_code == 500
    assert deleted == ["new-id:0"]


def test_delete_chroma_failure_keeps_mongo_document(monkeypatch):
    record = _doc("existing-id", vector_ids=["existing-id:0"])
    deleted_records = []
    monkeypatch.setattr(documents.models, "get_document", lambda document_id: record)

    def fail_delete(**kwargs):
        raise RuntimeError("Chroma delete failed")

    monkeypatch.setattr(documents, "delete_document_chunks", fail_delete)
    monkeypatch.setattr(documents.models, "delete_document", lambda document_id: deleted_records.append(document_id) or True)

    with pytest.raises(HTTPException) as error:
        documents.delete_document("existing-id", {"_id": "admin"})

    assert error.value.status_code == 503
    assert deleted_records == []
    assert record["vector_ids"] == ["existing-id:0"]


def test_chunk_delete_propagates_chroma_failure(monkeypatch):
    class BrokenCollection:
        def delete(self, **kwargs):
            raise RuntimeError("Chroma delete failed")

    monkeypatch.setattr(retriever, "get_chroma_collection", lambda: BrokenCollection())
    with pytest.raises(RuntimeError, match="Chroma delete failed"):
        retriever.delete_document_chunks(vector_ids=["doc:0"])
