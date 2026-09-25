"""
RAG vector store and retrieval utilities.

Phase 5:
- Generate embeddings through Gemini
- Store document chunks in ChromaDB
- Retrieve the most relevant chunks for a user query
"""

import os
from pathlib import Path
from typing import List, Dict

import chromadb
from dotenv import load_dotenv
from google import genai
from google.genai import types


# -------------------------------------------------------------------
# Load backend/.env
# -------------------------------------------------------------------

BACKEND_DIR = Path(__file__).resolve().parents[1]

load_dotenv(BACKEND_DIR / ".env")


# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

# Gemini embedding model.
#
# 768 dimensions are used for the ChromaDB vectors.
#
# IMPORTANT:
# The previous OpenRouter/OpenAI embeddings cannot be mixed
# with Gemini embeddings. The existing RAG index will need
# to be rebuilt after migration.

EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSION = 768

CHROMA_DIR = BACKEND_DIR / "rag" / "chroma_db"

COLLECTION_NAME = "support_documents"


# -------------------------------------------------------------------
# Gemini client
# -------------------------------------------------------------------

provider = os.getenv("PROVIDER", "gemini").lower()

if provider != "gemini":
    raise RuntimeError(
        "RAG embeddings are configured for Gemini. "
        "Set PROVIDER=gemini in backend/.env"
    )


google_api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("API_KEY")

if not google_api_key:
    raise RuntimeError(
        "GOOGLE_API_KEY or API_KEY is not configured "
        "in backend/.env"
    )


gemini_client = genai.Client(
    api_key=google_api_key
)


# -------------------------------------------------------------------
# Chroma client
# -------------------------------------------------------------------

chroma_client = chromadb.PersistentClient(
    path=str(CHROMA_DIR)
)


collection = chroma_client.get_or_create_collection(
    name=COLLECTION_NAME,
    metadata={
        "description": (
            "Customer support policy and knowledge documents"
        )
    },
)


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

    response = gemini_client.models.embed_content(
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
    Generate an embedding for a user's search query
    using Gemini.
    """

    if not query.strip():
        return []

    response = gemini_client.models.embed_content(
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
) -> int:
    """
    Embed and store document chunks in ChromaDB.
    """

    if not chunks:
        return 0

    embeddings = embed_documents(chunks)

    ids = [
        f"{Path(source).stem}_{index}"
        for index in range(len(chunks))
    ]

    metadatas = [
        {
            "source": source,
            "chunk_index": index,
        }
        for index in range(len(chunks))
    ]

    collection.upsert(
        ids=ids,
        documents=chunks,
        embeddings=embeddings,
        metadatas=metadatas,
    )

    return len(chunks)


# -------------------------------------------------------------------
# Retrieval
# -------------------------------------------------------------------

def search_documents(
    query: str,
    top_k: int = 5,
) -> List[Dict]:
    """
    Retrieve the most relevant document chunks for a user query.
    """

    if not query.strip():
        return []

    query_embedding = embed_query(query)

    if not query_embedding:
        return []

    document_count = collection.count()

    if document_count == 0:
        return []

    top_k = min(top_k, document_count)

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
    )

    documents = results.get(
        "documents",
        [[]],
    )[0]

    metadatas = results.get(
        "metadatas",
        [[]],
    )[0]

    distances = results.get(
        "distances",
        [[]],
    )[0]

    retrieved = []

    for document, metadata, distance in zip(
        documents,
        metadatas,
        distances,
    ):
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

def collection_count() -> int:
    """
    Return the number of chunks currently stored.
    """

    return collection.count()


# -------------------------------------------------------------------
# Delete document chunks
# -------------------------------------------------------------------

def delete_document_chunks(
    source: str,
) -> int:
    """
    Delete all ChromaDB chunks belonging to a document source.
    """

    if not source:
        return 0

    results = collection.get(
        where={
            "source": source
        }
    )

    ids = results.get(
        "ids",
        [],
    )

    if not ids:
        return 0

    collection.delete(
        ids=ids
    )

    return len(ids)