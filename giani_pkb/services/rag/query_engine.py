# File: giani_pkb/services/rag/query_engine.py
from typing import Optional
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.response_synthesizers import CompactAndRefine
from llama_index.core import VectorStoreIndex
from giani_pkb.services.rag.retriever_service import build_metadata_filtered_retriever

def build_query_engine(
    index: VectorStoreIndex,
    project_id: int,
    document_content_type: Optional[str] = None,
    top_k: int = 5
) -> RetrieverQueryEngine:
    retriever = build_metadata_filtered_retriever(index, project_id, document_content_type, top_k)
    return RetrieverQueryEngine(
        retriever=retriever,
        response_synthesizer=CompactAndRefine()
    )