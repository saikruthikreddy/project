import logging
from typing import Optional, List
from llama_index.core import VectorStoreIndex
from llama_index.core.retrievers import VectorIndexRetriever, BaseRetriever
from llama_index.core.vector_stores.types import MetadataFilter, MetadataFilters
from llama_index.core.postprocessor import LLMRerank

logger = logging.getLogger(__name__)

def build_metadata_filtered_retriever(
    index: VectorStoreIndex,
    project_id: int,
    document_content_type: Optional[str] = None,
    top_k: int = 5,
    rerank_top_n: int = 5,
) -> BaseRetriever:
    """
    Build a retriever with metadata filtering and LLM-based reranking.
    
    Args:
        index: Vector index instance
        project_id: Project identifier
        document_content_type: Optional document content type
        top_k: Number of documents to retrieve before reranking
        rerank_top_n: Number of top results to keep after reranking
        
    Returns:
        A retriever with LLM reranking
    """
    try:
        # Step 1: Build metadata filters
        filters: List[MetadataFilter] = [
            MetadataFilter(key="project_id", value=project_id)
        ]
        if document_content_type:
            filters.append(MetadataFilter(key="document_type", value=document_content_type))

        metadata_filters = MetadataFilters(filters=filters)

        # Step 2: Build base retriever
        retriever = index.as_retriever(
            similarity_top_k=top_k,
            filters=metadata_filters
        )

        # Step 3: Attach reranker
        reranker = LLMRerank(top_n=rerank_top_n)

        # Attach postprocessors (reranker acts as one)
        retriever.postprocessors = [reranker]

        logger.debug(f"Built retriever with reranking: top_k={top_k}, rerank_top_n={rerank_top_n}, filters={filters}")

        return retriever

    except Exception as e:
        logger.error(f"Failed to build metadata-filtered retriever with reranking: {str(e)}")
        raise