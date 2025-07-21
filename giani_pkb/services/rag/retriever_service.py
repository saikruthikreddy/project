import logging
from typing import Optional, List
from llama_index.core.vector_stores.types import MetadataFilter, MetadataFilters, FilterOperator
from llama_index.core.indices import VectorStoreIndex
from llama_index.core.retrievers import VectorIndexRetriever

logger = logging.getLogger(__name__)

def build_metadata_filtered_retriever(
    index: VectorStoreIndex,
    project_id: int,
    document_content_type: Optional[str] = None,
    top_k: int = 5,
    similarity_threshold: float = 0.7
) -> VectorIndexRetriever:
    """
    Build a retriever with metadata filtering and similarity thresholding.
    
    Args:
        index: The vector store index
        project_id: Project identifier for filtering
        document_content_type: Optional document type filter
        top_k: Number of chunks to retrieve
        similarity_threshold: Minimum similarity score
        
    Returns:
        Configured VectorIndexRetriever
    """
    try:
        # Build filters
        filters: List[MetadataFilter] = [
            MetadataFilter(
                key="project_id", 
                value=project_id,
                operator=FilterOperator.EQ
            )
        ]
        
        if document_content_type:
            filters.append(
                MetadataFilter(
                    key="document_type", 
                    value=document_content_type,
                    operator=FilterOperator.EQ
                )
            )
        
        metadata_filters = MetadataFilters(
            filters=filters,
            condition="and"  # All filters must match
        )
        
        retriever = index.as_retriever(
            similarity_top_k=top_k,
            filters=metadata_filters
        )
        
        # Add similarity threshold if supported by the vector store
        if hasattr(retriever, 'similarity_cutoff'):
            retriever.similarity_cutoff = similarity_threshold
            
        logger.debug(f"Built retriever with {len(filters)} filters, top_k={top_k}")
        return retriever
        
    except Exception as e:
        logger.error(f"Failed to build retriever: {str(e)}")
        raise