# File: giani_pkb/services/rag/retriever_service.py
from typing import Optional
from llama_index.core.vector_stores.types import MetadataFilter, MetadataFilters
from llama_index.core.indices import VectorStoreIndex

def build_metadata_filtered_retriever(
    index: VectorStoreIndex,
    project_id: int,
    document_content_type: Optional[str] = None,
    top_k: int = 5
):
    filters = [
        MetadataFilter(key="project_id", value=project_id)
    ]
    if document_content_type:
        filters.append(MetadataFilter(key="document_type", value=document_content_type))

    return index.as_retriever(
        similarity_top_k=top_k,
        filters=MetadataFilters(filters=filters)
    )