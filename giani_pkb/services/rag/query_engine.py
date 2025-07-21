import logging
from typing import Optional
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.response_synthesizers import CompactAndRefine
from llama_index.core import VectorStoreIndex
from giani_pkb.services.rag.retriever_service import build_metadata_filtered_retriever

logger = logging.getLogger(__name__)

def build_query_engine(
    index: VectorStoreIndex,
    project_id: int,
    document_content_type: Optional[str] = None,
    top_k: int = 5,
    similarity_threshold: float = 0.7,
    streaming: bool = False
) -> RetrieverQueryEngine:
    """
    Build a query engine with proper configuration.
    
    Args:
        index: The vector store index
        project_id: Project identifier for filtering
        document_content_type: Optional document type filter
        top_k: Number of chunks to retrieve
        similarity_threshold: Minimum similarity score
        streaming: Whether to enable streaming responses
        
    Returns:
        Configured RetrieverQueryEngine
    """
    try:
        retriever = build_metadata_filtered_retriever(
            index, 
            project_id, 
            document_content_type, 
            top_k
        )
        
        # Configure response synthesizer with better settings
        response_synthesizer = CompactAndRefine(
            text_qa_template=None,  # Use default or customize
            refine_template=None,   # Use default or customize
            streaming=streaming
        )
        
        return RetrieverQueryEngine(
            retriever=retriever,
            response_synthesizer=response_synthesizer
        )
        
    except Exception as e:
        logger.error(f"Failed to build query engine: {str(e)}")
        raise