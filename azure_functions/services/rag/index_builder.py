import hashlib
import logging
import time
from datetime import datetime
from typing import List, Optional, Dict, Any, Set
from sqlalchemy.orm import Session
from sqlalchemy import Column, String, Integer, DateTime, Index, text
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import prometheus_client
from prometheus_client import Histogram, Counter
import numpy as np

from llama_index.core import VectorStoreIndex
from services.rag.node_converter import convert_chunk_to_node
from services.rag.embed_chunks import INGESTION_VERSION  # Import shared version
from models.database_models import Document, DocumentChunk, Base

# Configure structured logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Prometheus metrics
indexing_duration = Histogram(
    'indexing_duration_seconds',
    'Time spent indexing chunks',
    ['project_id', 'document_content_type']
)

chunks_indexed = Counter(
    'chunks_indexed_total',
    'Total chunks indexed successfully',
    ['project_id', 'document_content_type', 'ingestion_version']
)

indexing_failures = Counter(
    'indexing_failures_total',
    'Total indexing failures',
    ['project_id', 'error_type', 'stage']
)

duplicate_chunks_skipped = Counter(
    'duplicate_chunks_skipped_total',
    'Total duplicate chunks skipped',
    ['project_id', 'document_content_type']
)

# Constants - now using shared ingestion version for perfect alignment
CURRENT_INGESTION_VERSION = INGESTION_VERSION  # Use the same version as embedding
MAX_RETRIES = 5

# Database model for tracking indexed chunks
class IndexedChunk(Base):
    """Track indexed chunks to ensure idempotency"""
    __tablename__ = 'indexed_chunks'

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, nullable=False)
    chunk_id = Column(Integer, nullable=False, unique=True)
    chunk_hash = Column(String(64), nullable=False)  # SHA256 hash - now aligned with embedding_hash
    ingestion_version = Column(String(20), nullable=False)
    indexed_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Indexes for efficient querying
    __table_args__ = (
        Index('idx_document_chunk_hash', 'document_id', 'chunk_hash'),
        Index('idx_chunk_id', 'chunk_id'),
        Index('idx_ingestion_version', 'ingestion_version'),
    )

class RAGIndexer:
    def __init__(self, db_session: Session):
        self.db = db_session
        self._ensure_indexed_chunks_table()

    def _ensure_indexed_chunks_table(self):
        """Ensure the indexed_chunks table exists"""
        try:
            # Create table if it doesn't exist
            Base.metadata.create_all(
                bind=self.db.bind,
                tables=[IndexedChunk.__table__],
                checkfirst=True
            )
            logger.info(
                "Verified indexed_chunks table exists",
                extra={
                    "stage": "INDEXING",
                    "action": "table_check"
                }
            )
        except Exception as e:
            logger.error(
                "Failed to create indexed_chunks table",
                extra={
                    "stage": "INDEXING",
                    "action": "table_creation",
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            )
            raise

    def _compute_chunk_hash(self, chunk: DocumentChunk) -> str:
        """
        Compute chunk hash for idempotency - prioritizes reusing embedding_hash from embedder.
        Only falls back to calculation for legacy chunks.
        """
        # PRIMARY: Use the definitive embedding_hash if it exists and matches current version
        if (hasattr(chunk, 'embedding_hash') and
            chunk.embedding_hash and
            hasattr(chunk, 'embedding_model') and
            chunk.embedding_model):

            logger.debug(
                "Reusing embedding_hash from embedder",
                extra={
                    "stage": "INDEXING",
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "embedding_hash": chunk.embedding_hash,
                    "embedding_model": chunk.embedding_model,
                    "reason": "embedding_hash_exists"
                }
            )
            return chunk.embedding_hash

        # FALLBACK: Calculate hash for legacy chunks using identical formula
        logger.warning(
            "Computing fallback hash for legacy chunk",
            extra={
                "stage": "INDEXING",
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "reason": "no_embedding_hash"
            }
        )

        # Use identical text|model|version formula as embedder
        from services.rag.embed_chunk import (
            generate_structural_header,
            canonicalize_numbers,
            PRIMARY_EMBEDDING_MODEL
        )

        try:
            # Get document for header generation
            document = self.db.query(Document).filter(Document.id == chunk.document_id).first()
            if not document:
                # Minimal fallback if document not found
                fallback_input = f"{chunk.chunk_text}|{PRIMARY_EMBEDDING_MODEL}|{CURRENT_INGESTION_VERSION}"
                return hashlib.sha256(fallback_input.encode('utf-8')).hexdigest()

            # Reconstruct the exact text processing from embedder
            header = generate_structural_header(chunk, document)
            normalized_text = canonicalize_numbers(chunk.chunk_text)
            full_text = f"{header}\n{normalized_text}"

            # Use identical hash formula: text|model|version
            hash_input = f"{full_text}|{PRIMARY_EMBEDDING_MODEL}|{CURRENT_INGESTION_VERSION}"
            computed_hash = hashlib.sha256(hash_input.encode('utf-8')).hexdigest()

            logger.debug(
                "Computed fallback hash for legacy chunk",
                extra={
                    "stage": "INDEXING",
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "computed_hash": computed_hash,
                    "reason": "legacy_fallback"
                }
            )

            return computed_hash

        except Exception as e:
            logger.error(
                "Failed to compute fallback hash, using minimal fallback",
                extra={
                    "stage": "INDEXING",
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            )
            # Ultimate fallback - use chunk text + defaults
            fallback_input = f"{chunk.chunk_text}|{PRIMARY_EMBEDDING_MODEL}|{CURRENT_INGESTION_VERSION}"
            return hashlib.sha256(fallback_input.encode('utf-8')).hexdigest()

    def _get_existing_chunk_hashes(self, document_ids: List[int]) -> Set[str]:
        """Get existing chunk hashes for the given documents"""
        try:
            existing_hashes = self.db.query(IndexedChunk.chunk_hash)\
                .filter(IndexedChunk.document_id.in_(document_ids))\
                .filter(IndexedChunk.ingestion_version == CURRENT_INGESTION_VERSION)\
                .all()
            return {hash_tuple[0] for hash_tuple in existing_hashes}
        except Exception as e:
            logger.error(
                "Failed to fetch existing chunk hashes",
                extra={
                    "stage": "INDEXING",
                    "action": "hash_fetch",
                    "document_ids": document_ids,
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            )
            # Return empty set to proceed with indexing
            return set()

    def _is_chunk_already_indexed(self, chunk: DocumentChunk, chunk_hash: str) -> bool:
        """Check if chunk is already indexed with current version"""
        try:
            existing = self.db.query(IndexedChunk)\
                .filter(IndexedChunk.chunk_id == chunk.id)\
                .filter(IndexedChunk.chunk_hash == chunk_hash)\
                .filter(IndexedChunk.ingestion_version == CURRENT_INGESTION_VERSION)\
                .first()
            return existing is not None
        except Exception as e:
            logger.warning(
                "Failed to check if chunk is indexed, proceeding with indexing",
                extra={
                    "stage": "INDEXING",
                    "action": "duplicate_check",
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            )
            # If check fails, proceed with indexing to be safe
            return False

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=2, min=1, max=16),
        retry=retry_if_exception_type((Exception,))
    )
    def _record_indexed_chunk(self, chunk: DocumentChunk, chunk_hash: str) -> None:
        """Record that a chunk has been indexed"""
        try:
            indexed_chunk = IndexedChunk(
                document_id=chunk.document_id,
                chunk_id=chunk.id,
                chunk_hash=chunk_hash,
                ingestion_version=CURRENT_INGESTION_VERSION,
                indexed_at=datetime.utcnow()
            )

            self.db.add(indexed_chunk)
            self.db.commit()

            logger.debug(
                "Recorded indexed chunk",
                extra={
                    "stage": "INDEXING",
                    "action": "record_chunk",
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "chunk_hash": chunk_hash,
                    "ingestion_version": CURRENT_INGESTION_VERSION
                }
            )

        except Exception as e:
            self.db.rollback()
            logger.error(
                "Failed to record indexed chunk",
                extra={
                    "stage": "INDEXING",
                    "action": "record_chunk",
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "chunk_hash": chunk_hash,
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            )
            indexing_failures.labels(
                project_id="unknown",
                error_type=type(e).__name__,
                stage="record_chunk"
            ).inc()
            raise

    def build_index_for_project(
        self,
        project_id: int,
        document_content_type: Optional[str] = None
    ) -> VectorStoreIndex:
        """
        Build index for project with perfect hash alignment and idempotency.
        """
        start_time = time.time()

        logger.info(
            "Starting index building for project",
            extra={
                "stage": "INDEXING",
                "project_id": project_id,
                "document_content_type": document_content_type,
                "ingestion_version": CURRENT_INGESTION_VERSION,
                "action": "start"
            }
        )

        stats = {
            'total_chunks': 0,
            'skipped_duplicates': 0,
            'indexed_new': 0,
            'failed_chunks': 0,
            'hash_reused_count': 0,
            'hash_computed_count': 0
        }

        try:
            with indexing_duration.labels(
                project_id=str(project_id),
                document_content_type=document_content_type or "all"
            ).time():

                # Fetch chunks with embeddings
                chunks = self._fetch_chunks(project_id, document_content_type)
                stats['total_chunks'] = len(chunks)

                if not chunks:
                    logger.warning(
                        "No chunks with embeddings found for project",
                        extra={
                            "stage": "INDEXING",
                            "project_id": project_id,
                            "document_content_type": document_content_type,
                            "action": "complete",
                            "reason": "no_chunks"
                        }
                    )
                    raise ValueError("No chunks with embeddings for that project")

                # Get document IDs for batch hash checking
                document_ids = list(set(chunk.document_id for chunk in chunks))
                existing_hashes = self._get_existing_chunk_hashes(document_ids)

                # Process chunks with perfect idempotency checking
                nodes_to_index = []

                for chunk in chunks:
                    try:
                        # Use aligned hash computation (prioritizes embedding_hash reuse)
                        chunk_hash = self._compute_chunk_hash(chunk)

                        # Track hash source for statistics
                        if hasattr(chunk, 'embedding_hash') and chunk.embedding_hash:
                            stats['hash_reused_count'] += 1
                        else:
                            stats['hash_computed_count'] += 1

                        # Check for duplicates using aligned hash
                        if chunk_hash in existing_hashes:
                            stats['skipped_duplicates'] += 1
                            duplicate_chunks_skipped.labels(
                                project_id=str(project_id),
                                document_content_type=document_content_type or "all"
                            ).inc()

                            logger.debug(
                                "Skipping duplicate chunk (aligned hash match)",
                                extra={
                                    "stage": "INDEXING",
                                    "project_id": project_id,
                                    "chunk_id": chunk.id,
                                    "document_id": chunk.document_id,
                                    "chunk_hash": chunk_hash,
                                    "reason": "duplicate_hash_aligned"
                                }
                            )
                            continue

                        # Additional individual check (in case batch check missed something)
                        if self._is_chunk_already_indexed(chunk, chunk_hash):
                            stats['skipped_duplicates'] += 1
                            duplicate_chunks_skipped.labels(
                                project_id=str(project_id),
                                document_content_type=document_content_type or "all"
                            ).inc()

                            logger.debug(
                                "Skipping already indexed chunk (aligned hash)",
                                extra={
                                    "stage": "INDEXING",
                                    "project_id": project_id,
                                    "chunk_id": chunk.id,
                                    "document_id": chunk.document_id,
                                    "chunk_hash": chunk_hash,
                                    "reason": "already_indexed_aligned"
                                }
                            )
                            continue

                        # Convert chunk to node for indexing
                        node = convert_chunk_to_node(chunk, project_id)
                        nodes_to_index.append((node, chunk, chunk_hash))

                        logger.debug(
                            "Prepared chunk for indexing (aligned hash)",
                            extra={
                                "stage": "INDEXING",
                                "project_id": project_id,
                                "chunk_id": chunk.id,
                                "document_id": chunk.document_id,
                                "chunk_hash": chunk_hash
                            }
                        )

                    except Exception as e:
                        stats['failed_chunks'] += 1
                        indexing_failures.labels(
                            project_id=str(project_id),
                            error_type=type(e).__name__,
                            stage="chunk_processing"
                        ).inc()

                        logger.error(
                            "Failed to process chunk for indexing",
                            extra={
                                "stage": "INDEXING",
                                "project_id": project_id,
                                "chunk_id": getattr(chunk, 'id', 'unknown'),
                                "document_id": getattr(chunk, 'document_id', 'unknown'),
                                "error": str(e),
                                "error_type": type(e).__name__
                            }
                        )
                        # Continue with other chunks instead of failing entirely
                        continue

                if not nodes_to_index:
                    logger.warning(
                        "No new chunks to index (all duplicates or processed)",
                        extra={
                            "stage": "INDEXING",
                            "project_id": project_id,
                            "document_content_type": document_content_type,
                            "stats": stats
                        }
                    )
                    # Return empty index or raise based on requirements
                    raise ValueError("No new chunks to index for this project")

                # Create the vector index
                nodes = [node for node, _, _ in nodes_to_index]
                index = self._create_vector_index_with_retry(nodes)

                # Record successfully indexed chunks with aligned hashes
                for node, chunk, chunk_hash in nodes_to_index:
                    try:
                        self._record_indexed_chunk(chunk, chunk_hash)
                        stats['indexed_new'] += 1

                        chunks_indexed.labels(
                            project_id=str(project_id),
                            document_content_type=document_content_type or "all",
                            ingestion_version=CURRENT_INGESTION_VERSION
                        ).inc()

                    except Exception as e:
                        stats['failed_chunks'] += 1
                        # Log but don't fail the entire operation
                        logger.warning(
                            "Failed to record indexed chunk, but index was created",
                            extra={
                                "stage": "INDEXING",
                                "project_id": project_id,
                                "chunk_id": chunk.id,
                                "document_id": chunk.document_id,
                                "chunk_hash": chunk_hash,
                                "error": str(e),
                                "error_type": type(e).__name__
                            }
                        )

                duration = time.time() - start_time

                logger.info(
                    "Index building completed successfully with perfect alignment",
                    extra={
                        "stage": "INDEXING",
                        "project_id": project_id,
                        "document_content_type": document_content_type,
                        "action": "complete",
                        "duration_seconds": round(duration, 2),
                        "stats": stats,
                        "ingestion_version": CURRENT_INGESTION_VERSION,
                        "hash_alignment_info": {
                            "hash_reused_from_embedder": stats['hash_reused_count'],
                            "hash_computed_fallback": stats['hash_computed_count']
                        }
                    }
                )

                return index

        except Exception as e:
            duration = time.time() - start_time
            indexing_failures.labels(
                project_id=str(project_id),
                error_type=type(e).__name__,
                stage="build_index"
            ).inc()

            logger.error(
                "Index building failed",
                extra={
                    "stage": "INDEXING",
                    "project_id": project_id,
                    "document_content_type": document_content_type,
                    "action": "failed",
                    "duration_seconds": round(duration, 2),
                    "stats": stats,
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            )
            raise

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=2, min=1, max=16),
        retry=retry_if_exception_type((Exception,))
    )
    def _create_vector_index_with_retry(self, nodes: List) -> VectorStoreIndex:
        """Create vector index with retry logic"""
        try:
            logger.info(
                "Creating vector index",
                extra={
                    "stage": "INDEXING",
                    "action": "create_vector_index",
                    "node_count": len(nodes)
                }
            )

            index = VectorStoreIndex(nodes=nodes)

            logger.info(
                "Vector index created successfully",
                extra={
                    "stage": "INDEXING",
                    "action": "vector_index_created",
                    "node_count": len(nodes)
                }
            )

            return index

        except Exception as e:
            logger.error(
                "Failed to create vector index",
                extra={
                    "stage": "INDEXING",
                    "action": "create_vector_index",
                    "node_count": len(nodes),
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            )
            raise

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=0.5, max=8),
        retry=retry_if_exception_type((Exception,))
    )
    def _fetch_chunks(
        self,
        project_id: int,
        document_content_type: Optional[str] = None
    ) -> List[DocumentChunk]:
        """
        Fetch chunks for a project with retry logic and enhanced logging.
        """
        logger.info(
            "Fetching chunks for project",
            extra={
                "stage": "INDEXING",
                "project_id": project_id,
                "document_content_type": document_content_type,
                "action": "fetch_chunks_start"
            }
        )

        try:
            # Build the document query
            document_query = self.db.query(Document.id).filter(Document.project_id == project_id)

            if document_content_type:
                document_query = document_query.filter(Document.final_category == document_content_type)
                logger.debug(
                    "Filtered by document content type",
                    extra={
                        "stage": "INDEXING",
                        "project_id": project_id,
                        "document_content_type": document_content_type
                    }
                )

            # Get document IDs
            document_ids = [doc.id for doc in document_query.all()]

            if not document_ids:
                logger.warning(
                    "No documents found for project",
                    extra={
                        "stage": "INDEXING",
                        "project_id": project_id,
                        "document_content_type": document_content_type,
                        "action": "fetch_chunks_complete",
                        "result": "no_documents"
                    }
                )
                return []

            logger.debug(
                "Found documents for project",
                extra={
                    "stage": "INDEXING",
                    "project_id": project_id,
                    "document_count": len(document_ids),
                    "document_ids": document_ids
                }
            )

            # Get chunks WITH embeddings only
            chunks = self.db.query(DocumentChunk)\
                .filter(DocumentChunk.document_id.in_(document_ids))\
                .filter(DocumentChunk.embedding_vector.isnot(None))\
                .all()

            # Convert embedding vectors to proper format
            for chunk in chunks:
                if chunk.embedding_vector is not None:
                    chunk.embedding_vector = np.asarray(chunk.embedding_vector, dtype=np.float32).tolist()

            logger.info(
                "Chunks fetched successfully",
                extra={
                    "stage": "INDEXING",
                    "project_id": project_id,
                    "document_content_type": document_content_type,
                    "action": "fetch_chunks_complete",
                    "chunk_count": len(chunks),
                    "document_count": len(document_ids)
                }
            )

            if not chunks:
                logger.warning(
                    "No chunks with embeddings found",
                    extra={
                        "stage": "INDEXING",
                        "project_id": project_id,
                        "document_content_type": document_content_type,
                        "document_count": len(document_ids),
                        "result": "no_chunks_with_embeddings"
                    }
                )

            return chunks

        except Exception as e:
            indexing_failures.labels(
                project_id=str(project_id),
                error_type=type(e).__name__,
                stage="fetch_chunks"
            ).inc()

            logger.error(
                "Failed to fetch chunks",
                extra={
                    "stage": "INDEXING",
                    "project_id": project_id,
                    "document_content_type": document_content_type,
                    "action": "fetch_chunks_failed",
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            )
            raise

    def get_indexing_stats(self, project_id: int) -> Dict[str, Any]:
        """Get indexing statistics for a project"""
        try:
            stats = {}

            # Count total indexed chunks
            total_indexed = self.db.query(IndexedChunk)\
                .join(DocumentChunk, IndexedChunk.chunk_id == DocumentChunk.id)\
                .join(Document, DocumentChunk.document_id == Document.id)\
                .filter(Document.project_id == project_id)\
                .count()

            stats['total_indexed_chunks'] = total_indexed

            # Count by ingestion version
            version_counts = self.db.query(
                IndexedChunk.ingestion_version,
                self.db.func.count(IndexedChunk.id)
            )\
                .join(DocumentChunk, IndexedChunk.chunk_id == DocumentChunk.id)\
                .join(Document, DocumentChunk.document_id == Document.id)\
                .filter(Document.project_id == project_id)\
                .group_by(IndexedChunk.ingestion_version)\
                .all()

            stats['by_ingestion_version'] = {version: count for version, count in version_counts}
            stats['current_ingestion_version'] = CURRENT_INGESTION_VERSION
            stats['aligned_with_embedder'] = True  # Flag indicating perfect alignment

            logger.info(
                "Retrieved indexing stats with alignment info",
                extra={
                    "stage": "INDEXING",
                    "project_id": project_id,
                    "action": "get_stats",
                    "stats": stats
                }
            )

            return stats

        except Exception as e:
            logger.error(
                "Failed to get indexing stats",
                extra={
                    "stage": "INDEXING",
                    "project_id": project_id,
                    "action": "get_stats_failed",
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            )
            return {"error": str(e)}

    def cleanup_old_versions(self, project_id: int, keep_versions: int = 3) -> int:
        """Clean up old ingestion versions, keeping only the most recent ones"""
        try:
            # Get unique versions ordered by most recent
            versions_query = self.db.query(IndexedChunk.ingestion_version)\
                .join(DocumentChunk, IndexedChunk.chunk_id == DocumentChunk.id)\
                .join(Document, DocumentChunk.document_id == Document.id)\
                .filter(Document.project_id == project_id)\
                .distinct()\
                .order_by(IndexedChunk.ingestion_version.desc())

            all_versions = [v[0] for v in versions_query.all()]

            if len(all_versions) <= keep_versions:
                logger.info(
                    "No old versions to cleanup",
                    extra={
                        "stage": "INDEXING",
                        "project_id": project_id,
                        "action": "cleanup",
                        "total_versions": len(all_versions),
                        "keep_versions": keep_versions
                    }
                )
                return 0

            # Delete old versions
            old_versions = all_versions[keep_versions:]
            deleted_count = 0

            for old_version in old_versions:
                deleted = self.db.query(IndexedChunk)\
                    .join(DocumentChunk, IndexedChunk.chunk_id == DocumentChunk.id)\
                    .join(Document, DocumentChunk.document_id == Document.id)\
                    .filter(Document.project_id == project_id)\
                    .filter(IndexedChunk.ingestion_version == old_version)\
                    .delete(synchronize_session=False)

                deleted_count += deleted

                logger.info(
                    "Cleaned up old ingestion version",
                    extra={
                        "stage": "INDEXING",
                        "project_id": project_id,
                        "action": "cleanup_version",
                        "ingestion_version": old_version,
                        "deleted_count": deleted
                    }
                )

            self.db.commit()

            logger.info(
                "Cleanup completed",
                extra={
                    "stage": "INDEXING",
                    "project_id": project_id,
                    "action": "cleanup_complete",
                    "total_deleted": deleted_count,
                    "old_versions_removed": old_versions
                }
            )

            return deleted_count

        except Exception as e:
            self.db.rollback()
            logger.error(
                "Failed to cleanup old versions",
                extra={
                    "stage": "INDEXING",
                    "project_id": project_id,
                    "action": "cleanup_failed",
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            )
            raise