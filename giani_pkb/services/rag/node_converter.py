import logging
from llama_index.core.schema import TextNode
from giani_pkb.models.database_models import DocumentChunk
import pandas as pd

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

def convert_chunk_to_node(chunk: DocumentChunk) -> TextNode:
    """
    Convert a DocumentChunk ORM object to a LlamaIndex TextNode,
    including all required metadata for filtering and logging.
    """
    try:
        # Ensure project_id and document_type can be accessed
        document = chunk.document  # Assuming relationship exists
        project_id = document.project_id if document else None
        document_type = document.final_category if document else None

        metadata = {
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "project_id": project_id,
            "document_type": document_type,
            "source_page_number": chunk.source_page_number,
            "structural_metadata": chunk.metadata_ or {},
            "created_at": str(chunk.created_at),
        }

        logger.debug(f"Converting chunk to node: ID={chunk.chunk_id}, metadata={metadata}")

        return TextNode(
            text=chunk.chunk_text,
            id_=str(chunk.chunk_id),
            metadata=metadata,
            embedding=chunk.embedding_vector
        )

    except Exception as e:
        logger.error(f"Error converting chunk {chunk.chunk_id} to node: {str(e)}")
        raise

def convert_row_to_node(row: pd.Series) -> TextNode:
    """
    Convert a DataFrame row into a TextNode.
    """
    try:
        metadata = {
            "chunk_id": row["chunk_id"],
            "document_id": row["document_id"],
            "project_id": row["project_id"],
            "source_page_number": eval(row["source_page_number"]),
            "structural_metadata": eval(row["structural_metadata"]),
            "document_content_type": row["document_content_type"],
            "created_at": row.get("created_at", ""),
        }

        logger.debug(f"Converting row to node: ID={row['chunk_id']}, metadata={metadata}")

        return TextNode(
            text=row["chunk_text_content"],
            id_=row["chunk_id"],
            metadata=metadata
        )

    except Exception as e:
        logger.error(f"Error converting row to node: {str(e)}")
        raise