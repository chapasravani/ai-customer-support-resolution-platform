"""
RAG document ingestion utilities.

Phase 5:
- Read supported documents
- Extract text
- Split text into chunks
- Prepare chunks for embedding/vector storage
"""

from pathlib import Path
from typing import List


SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}


def extract_text(file_path: str) -> str:
    """
    Extract text from a supported document.
    """

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    extension = path.suffix.lower()

    if extension in {".txt", ".md"}:
        return path.read_text(encoding="utf-8")

    if extension == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))

        pages = []
        for page in reader.pages:
            text = page.extract_text() or ""
            pages.append(text)

        return "\n".join(pages)

    raise ValueError(
        f"Unsupported file type: {extension}. "
        f"Supported types: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
    )


def split_text(
    text: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> List[str]:
    """
    Split text into overlapping chunks.
    """

    if not text.strip():
        return []

    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")

    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError(
            "chunk_overlap must be >= 0 and smaller than chunk_size"
        )

    text = text.strip()

    chunks = []
    start = 0
    text_length = len(text)

    while start < text_length:
        end = min(start + chunk_size, text_length)

        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end >= text_length:
            break

        start = end - chunk_overlap

    return chunks


def prepare_document(
    file_path: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> List[str]:
    """
    Extract text from a document and split it into chunks.
    """

    text = extract_text(file_path)

    return split_text(
        text,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )