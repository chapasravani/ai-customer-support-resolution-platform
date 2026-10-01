import asyncio
import logging
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from .. import models
from ..deps import require_admin
from ..rag.ingest import prepare_document
from ..rag.retriever import (
    add_document_chunks,
    delete_document_chunks,
)


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/documents",
    tags=["documents"],
)


SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB limit


def _serialize(d: dict) -> dict:
    return {
        "id": str(d["_id"]),
        "filename": d["filename"],
        "status": d["status"],
        "chunk_count": d.get("chunk_count", 0),
        "upload_date": d["upload_date"],
    }


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    admin: dict = Depends(require_admin),
    replace_document_id: str | None = Form(None),
):
    """
    Upload a support document and index it into the RAG vector store.
    """

    filename = file.filename or "uploaded_document"
    extension = Path(filename).suffix.lower()

    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported file type. "
                "Only PDF, TXT, and MD files are supported."
            ),
        )

    # Read uploaded file.
    file_bytes = await file.read()

    if not file_bytes:
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is empty.",
        )

    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="File size exceeds the 10MB limit.",
        )

    old_document = None
    if replace_document_id:
        old_document = models.get_document(replace_document_id)
        if not old_document:
            raise HTTPException(status_code=404, detail="Document to replace not found.")

    # Create MongoDB document record first.
    doc = models.create_document_record(
        filename=filename,
        uploaded_by=str(admin["_id"]),
    )

    document_id = str(doc["_id"])
    temp_path = None
    vector_ids = []

    try:
        # Save temporarily so the RAG ingestion code
        # can process PDF/TXT/MD files.
        with NamedTemporaryFile(
            delete=False,
            suffix=extension,
        ) as temp_file:
            temp_file.write(file_bytes)
            temp_path = temp_file.name

        # Extract text and create chunks off the event loop.
        chunks = await asyncio.to_thread(prepare_document, temp_path)

        if not chunks:
            raise ValueError(
                "No readable text was found in the uploaded document."
            )

        # add_document_chunks uses this exact ID scheme. Keep the IDs before
        # indexing so a partial Chroma write can be rolled back if it raises.
        vector_ids = [f"{document_id}:{index}" for index in range(len(chunks))]

        # Generate embeddings and store chunks in ChromaDB off the event loop (H2: keyed by document_id).
        stored_ids = await asyncio.to_thread(
            add_document_chunks,
            chunks=chunks,
            source=filename,
            document_id=document_id,
        )
        if isinstance(stored_ids, list):
            vector_ids = stored_ids
        chunk_count = len(vector_ids)

        # Update MongoDB document status with exact vector IDs (H2).
        models.update_document_status(
            document_id=document_id,
            status="indexed",
            chunk_count=chunk_count,
            vector_ids=vector_ids,
        )

        if old_document:
            old_vector_ids = old_document.get("vector_ids") or []
            await asyncio.to_thread(
                delete_document_chunks,
                vector_ids=old_vector_ids,
            )
            models.update_document_status(
                document_id=replace_document_id,
                status="superseded",
            )

        # Read the updated document record.
        updated_doc = models.get_document(document_id)

        return _serialize(updated_doc or doc)

    except ValueError as exc:
        if vector_ids:
            try:
                await asyncio.to_thread(delete_document_chunks, vector_ids=vector_ids)
            except Exception:
                logger.exception("Could not roll back chunks for failed document %s", document_id)
        models.update_document_status(
            document_id=document_id,
            status="failed",
        )
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except HTTPException:
        if vector_ids:
            try:
                await asyncio.to_thread(delete_document_chunks, vector_ids=vector_ids)
            except Exception:
                logger.exception("Could not roll back chunks for failed document %s", document_id)
        models.update_document_status(
            document_id=document_id,
            status="failed",
        )
        raise

    except Exception as exc:
        logger.exception("Document processing failed: %s", exc)
        if vector_ids:
            try:
                await asyncio.to_thread(delete_document_chunks, vector_ids=vector_ids)
            except Exception:
                logger.exception("Could not roll back chunks for failed document %s", document_id)
        models.update_document_status(
            document_id=document_id,
            status="failed",
        )
        raise HTTPException(
            status_code=500,
            detail="Document processing failed due to an internal server error.",
        )

    finally:
        # Remove temporary uploaded file.
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                pass


@router.get("")
def list_documents(
    admin: dict = Depends(require_admin),
):
    return [
        _serialize(d)
        for d in models.list_documents()
    ]


@router.delete("/{document_id}")
def delete_document(
    document_id: str,
    admin: dict = Depends(require_admin),
):
    document = models.get_document(document_id)

    if not document:
        raise HTTPException(
            404,
            "Document not found.",
        )

    filename = document.get("filename", "")
    vector_ids = document.get("vector_ids") or []

    try:
        deleted_chunks = delete_document_chunks(
            source=filename,
            vector_ids=vector_ids if vector_ids else None,
            document_id=document_id,
        )
    except Exception as exc:
        logger.exception("Could not delete chunks for document %s", document_id)
        raise HTTPException(
            status_code=503,
            detail="Document vectors could not be deleted. The document remains available for retry.",
        ) from exc

    deleted = models.delete_document(
        document_id
    )

    if not deleted:
        raise HTTPException(
            404,
            "Document not found.",
        )

    return {
        "status": "deleted",
        "filename": filename,
        "deleted_chunks": deleted_chunks,
    }
