# File: giani_pkb/services/rag/index_builder.py
from sqlalchemy.orm import Session
from typing import List, Optional
from llama_index.core import VectorStoreIndex
from giani_pkb.services.rag.node_converter import convert_chunk_to_node
from giani_pkb.models.database_models import Document, DocumentChunk
import numpy as np

class RAGIndexer:
    def __init__(self, db_session: Session):
        self.db = db_session

    def build_index_for_project(self, project_id: int, document_content_type: Optional[str] = None) -> VectorStoreIndex:
        print("inside build index")
        chunks = self._fetch_chunks(project_id, document_content_type)
        print("saeved cgunks")
        if not chunks:
            raise ValueError("No chunks with embeddings for that project")
        nodes = [convert_chunk_to_node(chunk) for chunk in chunks]
        return VectorStoreIndex(nodes=nodes) 

    def _fetch_chunks(self, project_id: int, document_content_type: Optional[str] = None) -> List[DocumentChunk]:
        """Fetch chunks for a project, optionally filtered by document content type."""
        print("inside fetchchunks")
        
        # Build the document query
        document_query = self.db.query(Document.id).filter(Document.project_id == project_id)
        
        if document_content_type:
            document_query = document_query.filter(Document.final_category == document_content_type)
        
        # Get document IDs
        document_ids = [doc.id for doc in document_query.all()]
        
        if not document_ids:
            print("No documents found for project")
            return []
        
        # Get chunks WITH embeddings only
        chunks = self.db.query(DocumentChunk)\
            .filter(DocumentChunk.document_id.in_(document_ids))\
            .filter(DocumentChunk.embedding_vector.isnot(None))\
            .all()

        for chunk in chunks:
            chunk.embedding_vector = np.asarray(chunk.embedding_vector, dtype=np.float32).tolist()
        
        print(f"Found {len(chunks)} chunks with embeddings")
        
        if not chunks:
            print("WARNING: No chunks with embeddings found!")
            
        return chunks
