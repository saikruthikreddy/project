from typing import List, Dict, Any, Optional
from datetime import datetime
from uuid import UUID
import uuid
from dataclasses import dataclass, field

from models.database_models import DocumentChunk

@dataclass
class ChunkDTO:
    """Data Transfer Object for chunk data - no database dependencies"""
    chunk_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    document_id: UUID = None
    chunk_index: int = 0
    chunk_text: str = ""
    source_page_numbers: List[int] = field(default_factory=list)
    metadata_: Dict[str, Any] = field(default_factory=dict)
    vector_id: Optional[str] = None
    embedding_vector: Optional[List[float]] = None
    embedding_model: str = "openai-embeddings"
    embedding_checksum: Optional[str] = None
    embedding_ts: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'chunk_id': self.chunk_id,
            'document_id': str(self.document_id) if self.document_id else None,
            'chunk_index': self.chunk_index,
            'chunk_text': self.chunk_text,
            'source_page_numbers': self.source_page_numbers,
            'metadata_': self.metadata_,
            'vector_id': self.vector_id,
            'embedding_vector': self.embedding_vector,
            'embedding_model': self.embedding_model,
            'embedding_checksum': self.embedding_checksum,
            'embedding_ts': self.embedding_ts.isoformat() if self.embedding_ts else None,
        }

    def to_document_chunk(self) -> 'DocumentChunk':
      """Convert DTO to SQLAlchemy model (for database operations)"""
      return DocumentChunk(
          chunk_id=self.chunk_id,
          document_id=self.document_id,
          chunk_index=self.chunk_index,
          chunk_text=self.chunk_text,
          source_page_numbers=self.source_page_numbers,
          metadata_=self.metadata_,
          vector_id=self.vector_id,
          embedding_vector=self.embedding_vector,
          embedding_model=self.embedding_model,
          embedding_checksum=self.embedding_checksum,
          embedding_ts=self.embedding_ts,
      )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ChunkDTO':
        """Create from dictionary"""
        # Handle UUID conversion
        document_id = data.get('document_id')
        if isinstance(document_id, str):
            document_id = UUID(document_id)

        # Handle datetime conversion
        embedding_ts = data.get('embedding_ts')
        if isinstance(embedding_ts, str):
            embedding_ts = datetime.fromisoformat(embedding_ts)

        return cls(
            chunk_id=data.get('chunk_id', str(uuid.uuid4())),
            document_id=document_id,
            chunk_index=data.get('chunk_index', 0),
            chunk_text=data.get('chunk_text', ''),
            source_page_numbers=data.get('source_page_numbers', []),
            metadata_=data.get('metadata_', {}),
            vector_id=data.get('vector_id'),
            embedding_vector=data.get('embedding_vector'),
            embedding_model=data.get('embedding_model', 'openai-embeddings'),
            embedding_checksum=data.get('embedding_checksum'),
            embedding_ts=embedding_ts,
        )

    @classmethod
    def from_document_chunk(cls, db_chunk: 'DocumentChunk') -> 'ChunkDTO':
        """Create DTO from SQLAlchemy model"""
        return cls(
            chunk_id=db_chunk.chunk_id,
            document_id=db_chunk.document_id,
            chunk_index=db_chunk.chunk_index,
            chunk_text=db_chunk.chunk_text,
            source_page_numbers=db_chunk.source_page_numbers or [],  # Note: field name diff
            metadata_=db_chunk.metadata_ or {},
            vector_id=db_chunk.vector_id,
            embedding_vector=db_chunk.embedding_vector,
            embedding_model=db_chunk.embedding_model,
            embedding_checksum=db_chunk.embedding_checksum,
            embedding_ts=db_chunk.embedding_ts,
        )

