import logging
from typing import Optional
from llama_index.core import VectorStoreIndex
from llama_index.core.retrievers import VectorIndexRetriever

logger = logging.getLogger(__name__)

def build_metadata_filtered_retriever(
    index: VectorStoreIndex,
    project_id: int,  # kept for interface compatibility
    document_content_type: Optional[str] = None,
    top_k: int = 5,
    similarity_threshold: float = 0.7
) -> VectorIndexRetriever:
    """
    Simplified retriever: no filtering, just returns top-k nodes.
    """
    try:
        retriever = index.as_retriever(similarity_top_k=top_k)
        logger.debug(f"Built retriever: top_k={top_k} (no filters applied)")
        return retriever

    except Exception as e:
        logger.error(f"Failed to build retriever: {str(e)}")
        raise