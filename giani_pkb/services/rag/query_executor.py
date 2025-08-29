import logging
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
import google.generativeai as genai
from giani_pkb.utils.config import GEMINI_FLASH_MODEL
from llama_index.core import VectorStoreIndex
from giani_pkb.services.rag.index_builder import RAGIndexer
from giani_pkb.services.rag.query_engine import build_query_engine
from giani_pkb.services.rag.citation_formatter import format_citations
from giani_pkb.services.rag.embed_chunks import embed_chunks_for_project

logger = logging.getLogger(__name__)

def run_query(
    db: Session,
    project_id: int,
    user_question: str,
    conversation_id: str = None,
    document_content_type: Optional[str] = None,
    top_k: int = 10,
    similarity_threshold: float = 0.7
) -> Dict[str, Any]:
    """Execute the RAG pipeline with improved error handling."""
    
    from giani_pkb.database.database_manager import DatabaseManager
    db_manager = DatabaseManager()

    try:
        if conversation_id:
            db_manager.add_chat_message(
                conversation_id=conversation_id,
                message=user_question,
                sender_type='human'
            )
        
        logger.info(f"Starting RAG query for project {project_id}: {user_question[:100]}...")

        embed_chunks_for_project(db, project_id)
        
        # Step 1: Indexing (existing code)
        indexer = RAGIndexer(db)
        logger.debug('Indexer initialized')
        
        try:
            index: VectorStoreIndex = indexer.build_index_for_project(
                project_id=project_id,
                document_content_type=document_content_type
            )
        except ValueError as e:
            if str(e) == "No chunks with embeddings for that project":
                logger.warning("No chunks with embeddings found for the project. Falling back to direct LLM call.")
                model = genai.GenerativeModel(GEMINI_FLASH_MODEL)
                response = model.generate_content(user_question)
                db_manager.add_chat_message(
                    conversation_id=conversation_id,
                    message=str(response.text),
                    sender_type='AI'
                )
                return {
                    "answer": response.text,
                    "sources": [],
                    "metadata": {
                        "chunks_retrieved": 0,
                        "query_successful": True,
                        "fallback_llm": True,
                        "project_id": project_id,
                        "document_type_filter": document_content_type
                    }
                }
            else:
                raise e

        if not index:
            raise ValueError(f"Failed to build index for project {project_id}")
        
        logger.debug('Index built successfully')
        
        # Step 2: Build query engine (existing code)
        query_engine = build_query_engine(
            index=index,
            project_id=project_id,
            document_content_type=document_content_type,
            top_k=top_k,
            similarity_threshold=similarity_threshold
        )
        
        logger.debug('Query engine built')
        
        # Step 3: Run query with better error handling
        try:
            logger.debug(f"Executing query: {user_question}")
            response = query_engine.query(user_question)
            logger.debug(f"Query response type: {type(response)}")
            logger.debug(f"Query response: {response}")
            
        except Exception as query_error:
            logger.error(f"Query execution failed: {str(query_error)}")
            logger.error(f"Query error type: {type(query_error)}")
            raise ValueError(f"Query execution error: {str(query_error)}")
        
        if not response:
            logger.warning(f"Empty response for query: {user_question}")
            return {
                "answer": "I couldn't find relevant information to answer your question.",
                "sources": [],
                "metadata": {
                    "chunks_retrieved": 0,
                    "query_successful": False
                }
            }

        if conversation_id:
            db_manager.add_chat_message(
                conversation_id=conversation_id,
                message=str(response),
                sender_type='AI'
            )
        
        # Step 4: Format citations
        sources = format_citations(response.source_nodes) if response.source_nodes else []
        
        logger.info(f"Query completed successfully. Retrieved {len(sources)} sources")
        
        return {
            "answer": str(response),
            "sources": sources,
            "metadata": {
                "chunks_retrieved": len(response.source_nodes) if response.source_nodes else 0,
                "query_successful": True,
                "project_id": project_id,
                "document_type_filter": document_content_type
            }
        }
        
    except Exception as e:
        error_msg = str(e) if str(e) else f"Unknown error of type {type(e).__name__}"
        logger.error(f"RAG query execution failed: {error_msg}")
        logger.error(f"Exception type: {type(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        return {
            "answer": f"An error occurred while processing your query: {error_msg}",
            "sources": [],
            "metadata": {
                "chunks_retrieved": 0,
                "query_successful": False,
                "error": error_msg
            }
        }
