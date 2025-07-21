# File: services/rag/node_converter.py
from llama_index.core.schema import TextNode
from giani_pkb.models.database_models import DocumentChunk
import pandas as pd

def convert_chunk_to_node(chunk: DocumentChunk) -> TextNode:
    """
    Convert a DocumentChunk ORM object to a LlamaIndex TextNode.
    All relevant metadata is carried into the node.
    """
    return TextNode(
        text=chunk.chunk_text,  # Fixed: was chunk_row.chunk_text_content
        id_=str(chunk.chunk_id),             # Fixed: was chunk_row.chunk_id
        metadata={
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "source_page_number": chunk.source_page_number,  # Already a JSON array
            "structural_metadata": chunk.metadata_ or {},
            "created_at": str(chunk.created_at),
        },
        embedding=chunk.embedding_vector  # Fixed: was chunk_row.embedding_vector
    )

def convert_row_to_node(row: pd.Series) -> TextNode:
    metadata = {
        "chunk_id": row["chunk_id"],
        "document_id": row["document_id"],
        "project_id": row["project_id"],
        "source_page_number": eval(row["source_page_number"]),  # if it's stored as stringified list
        "structural_metadata": eval(row["structural_metadata"]),
        "document_content_type": row["document_content_type"],
        "created_at": row.get("created_at", ""),
    }
    return TextNode(
        text=row["chunk_text_content"], 
        id_=row["chunk_id"], 
        metadata=metadata
    )