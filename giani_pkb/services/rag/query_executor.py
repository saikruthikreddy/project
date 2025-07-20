# File: services/rag/query_executor.py

from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from llama_index.core import VectorStoreIndex

from giani_pkb.services.rag.index_builder import RAGIndexer
from giani_pkb.services.rag.query_engine import build_query_engine
from giani_pkb.services.rag.citation_formatter import format_citations


def run_query(
    db: Session,
    project_id: int,
    user_question: str,
    document_content_type: Optional[str] = None,
    top_k: int = 10
) -> Dict[str, Any]:
    """
    Execute the RAG pipeline: fetch chunks, build index, run query, and return answer with citations.

    Args:
        db (Session): SQLAlchemy DB session.
        project_id (int): Project identifier to scope the query.
        user_question (str): The user's natural language question.
        document_content_type (Optional[str]): Optional filter by document type.
        top_k (int): Number of chunks to retrieve for context.

    Returns:
        Dict[str, Any]: Final answer and associated source citations.
    """
    # Step 1: Indexing
    indexer = RAGIndexer(db)
    index: VectorStoreIndex = indexer.build_index_for_project(
        project_id=project_id,
        document_content_type=document_content_type
    )

    # Step 2: Build query engine
    query_engine = build_query_engine(
        index=index,
        project_id=project_id,
        document_content_type=document_content_type,
        top_k=top_k
    )

    # Step 3: Run query
    response = query_engine.query(user_question)

    # Step 4: Format citations
    sources = format_citations(response.source_nodes)

    return {
        "answer": str(response),
        "sources": sources
    }