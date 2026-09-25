"""
RAG context helper.

Retrieves relevant support-policy/knowledge chunks from ChromaDB
and formats them so the ADK workflow can use them later.
"""

from typing import List

from .retriever import search_documents


def retrieve_support_context(
    query: str,
    top_k: int = 5,
) -> str:
    """
    Retrieve relevant support knowledge for a customer query
    and format it as context for the AI workflow.
    """

    results = search_documents(
        query=query,
        top_k=top_k,
    )

    if not results:
        return "No relevant support-policy information was found."

    context_parts: List[str] = []

    for index, result in enumerate(results, start=1):
        source = result.get("source", "unknown")
        content = result.get("content", "").strip()

        if not content:
            continue

        context_parts.append(
            f"[Source {index}: {source}]\n{content}"
        )

    if not context_parts:
        return "No relevant support-policy information was found."

    return "\n\n".join(context_parts)