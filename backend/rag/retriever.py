"""
RAG vector store and retrieval utilities.

Phase 5:
- Generate embeddings through Gemini
- Store document chunks in ChromaDB
- Retrieve the most relevant chunks for a user query
"""

import hashlib
import os
from pathlib import Path
from typing import Dict, List, Optional

import chromadb
from dotenv import load_dotenv


# -------------------------------------------------------------------
# Load backend/.env
# -------------------------------------------------------------------

BACKEND_DIR = Path(__file__).resolve().parents[1]

load_dotenv(BACKEND_DIR / ".env")


# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSION = 768

CHROMA_DIR = BACKEND_DIR / "rag" / "chroma_db"

COLLECTION_NAME = "support_documents"


# -------------------------------------------------------------------
# Lazy Clients & Collection (H3)
# -------------------------------------------------------------------

_gemini_client = None
_chroma_client = None
_collection = None


def get_gemini_client():
    """Lazily initialize Gemini client only when embedding operations are called (H3)."""
    global _gemini_client
    if _gemini_client is not None:
        return _gemini_client

    from google import genai

    provider = os.getenv("PROVIDER", "gemini").lower()
    if provider != "gemini":
        raise RuntimeError(
            "RAG embeddings are configured for Gemini. "
            "Set PROVIDER=gemini in backend/.env"
        )

    google_api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("API_KEY")
    if not google_api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY or API_KEY is not configured in backend/.env"
        )

    _gemini_client = genai.Client(api_key=google_api_key)
    return _gemini_client


def get_chroma_collection():
    """Lazily initialize ChromaDB collection only when vector store operations are called (H3)."""
    global _chroma_client, _collection
    if _collection is not None:
        return _collection

    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    _collection = _chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={
            "description": "Customer support policy and knowledge documents"
        },
    )
    return _collection


# -------------------------------------------------------------------
# Embeddings
# -------------------------------------------------------------------

def embed_documents(
    texts: List[str],
) -> List[List[float]]:
    """
    Generate embeddings for document chunks using Gemini.
    """
    if not texts:
        return []

    client = get_gemini_client()
    from google.genai import types

    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=texts,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_DOCUMENT",
            output_dimensionality=EMBEDDING_DIMENSION,
        ),
    )

    return [
        embedding.values
        for embedding in response.embeddings
    ]


def embed_query(
    query: str,
) -> List[float]:
    """
    Generate an embedding for a user's search query using Gemini.
    """
    if not query.strip():
        return []

    client = get_gemini_client()
    from google.genai import types

    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=query,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=EMBEDDING_DIMENSION,
        ),
    )

    return response.embeddings[0].values


# -------------------------------------------------------------------
# Chroma storage
# -------------------------------------------------------------------

def add_document_chunks(
    chunks: List[str],
    source: str,
    document_id: str = "",
) -> List[str]:
    """
    Embed and store document chunks in ChromaDB.
    Uses document_id as namespace for chunk IDs: f"{document_id}:{index}" (H2).
    """
    if not chunks:
        return []

    embeddings = embed_documents(chunks)

    if document_id:
        ids = [f"{document_id}:{index}" for index in range(len(chunks))]
    else:
        clean_stem = Path(source).stem[:24]
        ids = [
            f"{clean_stem}_{index}_{hashlib.sha256(f'{source}:{index}:{chunk}'.encode('utf-8')).hexdigest()[:12]}"
            for index, chunk in enumerate(chunks)
        ]

    metadatas = [
        {
            "source": source,
            "document_id": document_id,
            "chunk_index": index,
        }
        for index in range(len(chunks))
    ]

    col = get_chroma_collection()
    col.upsert(
        ids=ids,
        documents=chunks,
        embeddings=embeddings,
        metadatas=metadatas,
    )

    return ids


# -------------------------------------------------------------------
# Retrieval
# -------------------------------------------------------------------

def search_documents(
    query: str,
    top_k: int = 5,
) -> List[Dict]:
    """
    Retrieve the most relevant document chunks for a user query.
    An empty result means a healthy search found no matching content. Storage
    and embedding failures propagate so callers can report RAG as unavailable.
    """
    if not query.strip():
        return []

    col = get_chroma_collection()
    document_count = col.count()
    if document_count == 0:
        return []

    query_embedding = embed_query(query)
    if not query_embedding:
        return []

    top_k = min(top_k, document_count)
    results = col.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
    )

    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    retrieved = []
    for document, metadata, distance in zip(documents, metadatas, distances):
        retrieved.append(
            {
                "content": document,
                "source": metadata.get("source"),
                "chunk_index": metadata.get("chunk_index"),
                "distance": distance,
            }
        )

    return retrieved


# -------------------------------------------------------------------
# Collection count
# -------------------------------------------------------------------

def collection_count() -> Optional[int]:
    """
    Return the number of chunks currently stored.
    """
    try:
        return get_chroma_collection().count()
    except Exception:
        return None


# -------------------------------------------------------------------
# Delete document chunks
# -------------------------------------------------------------------

def delete_document_chunks(
    source: str = "",
    vector_ids: Optional[List[str]] = None,
    document_id: str = "",
) -> int:
    """
    Delete document chunks from ChromaDB.
    Deletes by exact vector_ids if provided (H2), or document_id, falling back to source metadata.
    """
    col = get_chroma_collection()
    if vector_ids:
        col.delete(ids=vector_ids)
        return len(vector_ids)
    if document_id:
        results = col.get(where={"document_id": document_id})
        ids = results.get("ids", [])
        if ids:
            col.delete(ids=ids)
            return len(ids)
        return 0
    if source:
        results = col.get(where={"source": source})
        ids = results.get("ids", [])
        if not ids:
            return 0
        col.delete(ids=ids)
        return len(ids)
    return 0
