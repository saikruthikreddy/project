"""
Chunk service for handling DocumentChunk operations with proper data flow.
"""

import logging
from typing import List, Optional, Dict, Any, Tuple
from uuid import UUID

from preprocessing.chunking.dto import ChunkDTO
from preprocessing.chunking.strategies import chunk_document_adaptive
from database.database_manager import DatabaseManager
from services.rag.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


class ChunkService:
    """
    Service layer for chunk operations following clean data flow patterns:
    - Database operations use SQLAlchemy models
    - Business logic uses DTOs
    - Clear conversion boundaries
    """

    def __init__(self):
        self.db_manager = DatabaseManager()
        self.embedding_service = EmbeddingService()

    def generate_chunks(
        self,
        parsed_blocks: List[Tuple[str, Dict[str, Any]]],
        document_id: UUID,
        project_id: int,
        document_type: str = "formal",
        openai_api_key: Optional[str] = None,
        **kwargs
    ) -> List[ChunkDTO]:
        """
        Generate chunks from parsed document blocks using adaptive chunking strategy.

        Args:
            parsed_blocks: List of (text, metadata) tuples from document processing
            document_id: UUID of the document
            project_id: Project ID
            document_type: Type of document for chunking strategy selection
            openai_api_key: OpenAI API key for semantic chunking (optional)
            **kwargs: Additional parameters for chunking strategies

        Returns:
            List of ChunkDTO objects ready for embedding and storage
        """
        try:
            chunk_dtos = chunk_document_adaptive(
                parsed_blocks=parsed_blocks,
                document_id=str(document_id),
                project_id=str(project_id),
                document_type=document_type,
                openai_api_key=openai_api_key,
                **kwargs
            )

            logger.info(f"Generated {len(chunk_dtos)} chunks for document {document_id}")
            return chunk_dtos

        except Exception as e:
            logger.error(f"Error generating chunks for document {document_id}: {e}")
            return []

    def get_chunks_for_document(self, document_id: UUID) -> List[ChunkDTO]:
        """
        Get all chunks for a document as DTOs for business logic use.
        """
        try:
            # Database layer returns SQLAlchemy models
            db_chunks = self.db_manager.get_document_chunks(document_id)

            # Convert to DTOs for business logic
            chunk_dtos = [ChunkDTO.from_document_chunk(chunk) for chunk in db_chunks]

            return chunk_dtos
        except Exception as e:
            logger.error(f"Error retrieving chunks for document {document_id}: {e}")
            return []

    def save_chunks(self, chunk_dtos: List[ChunkDTO]) -> bool:
        """
        Save chunks from DTOs to database.
        """
        try:
            # Convert DTOs to SQLAlchemy models for database operations
            db_chunks = [chunk_dto.to_document_chunk() for chunk_dto in chunk_dtos]

            # Use database manager to save
            document_id = chunk_dtos[0].document_id if chunk_dtos else None
            if document_id:
                self.db_manager.save_chunks(document_id, db_chunks)
                return True
            return False
        except Exception as e:
            logger.error(f"Error saving chunks: {e}")
            return False

    def embed_and_save_chunks(self, chunk_dtos: List[ChunkDTO]) -> Dict[str, int]:
        """
        Embed chunks and save them to database.
        Returns statistics about the operation.
        """
        stats = {
            'total_chunks': len(chunk_dtos),
            'embedded_successfully': 0,
            'embedding_failed': 0,
            'saved_successfully': 0
        }

        try:
            # Use the embedding service to embed DTOs directly
            embedding_stats = self.embedding_service.embed_chunk_dtos(chunk_dtos)
            stats.update(embedding_stats)

            # Convert embedded DTOs to SQLAlchemy models for database saving
            embedded_dtos = [dto for dto in chunk_dtos if dto.embedding_vector is not None]

            if embedded_dtos:
                db_chunks = [dto.to_document_chunk() for dto in embedded_dtos]
                document_id = chunk_dtos[0].document_id
                self.db_manager.save_chunks(document_id, db_chunks)
                stats['saved_successfully'] = len(db_chunks)

            return stats
        except Exception as e:
            logger.error(f"Error in embed_and_save_chunks: {e}")
            return stats

    async def embed_save_and_index_chunks(self, chunk_dtos: List[ChunkDTO]) -> Dict[str, int]:
        """
        Complete pipeline: embed chunks, save to database, and index in search service.
        Returns comprehensive statistics about all operations.
        """
        from services.ai_search_service import AzureSearchService

        stats = {
            'total_chunks': len(chunk_dtos),
            'embedded_successfully': 0,
            'embedding_failed': 0,
            'saved_successfully': 0,
            'indexed_successfully': 0,
            'indexing_failed': 0
        }

        try:
            # Step 1: Embed and save chunks
            embed_stats = self.embed_and_save_chunks(chunk_dtos)
            stats.update(embed_stats)

            # Step 2: Index successfully embedded chunks
            if embed_stats['embedded_successfully'] > 0:
                embedded_dtos = [dto for dto in chunk_dtos if dto.embedding_vector is not None]

                if embedded_dtos:
                    search_service = AzureSearchService()
                    try:
                        index_success = await search_service.index_document_chunks(embedded_dtos)
                        if index_success:
                            stats['indexed_successfully'] = len(embedded_dtos)
                        else:
                            stats['indexing_failed'] = len(embedded_dtos)
                    except Exception as e:
                        stats['indexing_failed'] = len(embedded_dtos)
                        logger.error(f"Error indexing chunks: {e}")

            return stats
        except Exception as e:
            logger.error(f"Error in embed_save_and_index_chunks: {e}")
            return stats

    def get_chunk_by_id(self, chunk_id: str) -> Optional[ChunkDTO]:
        """
        Get a single chunk by ID as DTO.
        """
        try:
            db_chunk = self.db_manager.get_chunk_by_id(chunk_id)
            if db_chunk:
                return ChunkDTO.from_document_chunk(db_chunk)
            return None
        except Exception as e:
            logger.error(f"Error retrieving chunk {chunk_id}: {e}")
            return None

    def update_chunk_embedding(self, chunk_id: str, embedding_vector: List[float],
                             embedding_checksum: str) -> bool:
        """
        Update chunk embedding information.
        """
        try:
            # Get as DTO for business logic
            chunk_dto = self.get_chunk_by_id(chunk_id)
            if not chunk_dto:
                return False

            # Update embedding info
            chunk_dto.embedding_vector = embedding_vector
            chunk_dto.embedding_checksum = embedding_checksum

            # Convert back to model and save
            db_chunk = chunk_dto.to_document_chunk()
            # Here you'd call a database update method
            # self.db_manager.update_chunk(db_chunk)

            return True
        except Exception as e:
            logger.error(f"Error updating chunk embedding {chunk_id}: {e}")
            return False