import asyncio
import logging
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

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

    # Create MongoDB document record first.
    doc = models.create_document_record(
        filename=filename,
        uploaded_by=str(admin["_id"]),
    )

    document_id = str(doc["_id"])
    temp_path = None

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

        # Generate embeddings and store chunks in ChromaDB off the event loop.
        chunk_count = await asyncio.to_thread(
            add_document_chunks,
            chunks=chunks,
            source=filename,
        )

        # Update MongoDB document status.
        models.update_document_status(
            document_id=document_id,
            status="indexed",
            chunk_count=chunk_count,
        )

        # Read the updated document record.
        updated_doc = models.get_document(document_id)

        return _serialize(updated_doc or doc)

    except ValueError as exc:
        models.update_document_status(
            document_id=document_id,
            status="failed",
        )
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except HTTPException:
        models.update_document_status(
            document_id=document_id,
            status="failed",
        )
        raise

    except Exception as exc:
        logger.exception("Document processing failed: %s", exc)
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

    deleted_chunks = delete_document_chunks(
        source=filename
    )

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