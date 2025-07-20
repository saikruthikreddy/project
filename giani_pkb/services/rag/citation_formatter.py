# File: services/rag/citation_formatter.py

from typing import List, Dict
from llama_index.core.schema import NodeWithScore


# File: giani_pkb/services/rag/citation_formatter.py
def format_citations(source_nodes):
    citations = []
    for node in source_nodes:
        meta = node.metadata
        citations.append({
            "chunk_id": node.node_id,
            "document_id": meta.get("document_id"),
            "project_id": meta.get("project_id"),
            "page_numbers": meta.get("page_numbers"),
            "document_type": meta.get("document_type"),
            "section_title": meta.get("section_title"),
        })
    return citations
