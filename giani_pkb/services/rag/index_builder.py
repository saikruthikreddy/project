# File: giani_pkb/services/rag/index_builder.py
from sqlalchemy.orm import Session
from typing import List, Optional
from llama_index.core import VectorStoreIndex
from giani_pkb.services.rag.node_converter import convert_chunk_to_node
from giani_pkb.models.database_models import DocumentChunk

class RAGIndexer:
    def __init__(self, db_session: Session):
        self.db = db_session

    def build_index_for_project(self, project_id: int, document_content_type: Optional[str] = None) -> VectorStoreIndex:
        chunks = self._fetch_chunks(project_id, document_content_type)
        nodes = [convert_chunk_to_node(chunk) for chunk in chunks]
        return VectorStoreIndex(nodes)

    def _fetch_chunks(self, project_id: int, document_content_type: Optional[str] = None) -> List[DocumentChunk]:
        query = self.db.query(DocumentChunk).filter(DocumentChunk.project_id == project_id)
        if document_content_type:
            query = query.filter(DocumentChunk.document_content_type == document_content_type)
        return query.all()