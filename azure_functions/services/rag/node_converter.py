from llama_index.core.schema import TextNode
from giani_pkb.models.database_models import DocumentChunk


def convert_chunk_to_node(chunk: DocumentChunk, project_id: int) -> TextNode:
    """
    Convert a DocumentChunk ORM object to a LlamaIndex TextNode,
    injecting the known project_id explicitly.
    """
    metadata = {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "project_id": project_id,
        "document_type": chunk.document.final_category if hasattr(chunk, "document") else None,
        "source_page_number": chunk.source_page_number,
        "structural_metadata": chunk.metadata_ or {},
        "created_at": str(chunk.created_at),
    }

    return TextNode(
        text=chunk.chunk_text,
        id_=str(chunk.chunk_id),
        metadata=metadata,
        embedding=chunk.embedding_vector
    )