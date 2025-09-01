"""
Embedding Service for handling chunk embeddings with clean data flow patterns.

This service provides both DTO-based methods (for service layer) and model-based methods (for database layer).
"""

import logging
import hashlib
import tiktoken
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple, Union
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from openai import OpenAI

from preprocessing.chunking.dto import ChunkDTO
from models.database_models import DocumentChunk, Document
from utils.config import config
from database.database_manager import DatabaseManager

logger = logging.getLogger(__name__)

# Initialize OpenAI client and tokenizer
openai = OpenAI(api_key=config.OPENAI_API_KEY)
tokenizer = tiktoken.encoding_for_model("text-embedding-3-small")

# Constants
EMBEDDING_MODEL = "text-embedding-3-small"
MAX_TOKENS_PER_CHUNK = 7500
MAX_TOKENS_PER_BATCH = 100000
MAX_RETRIES = 5
CHUNK_BATCH_SIZE = 96

class EmbeddingService:
    """
    Service for handling embeddings with clean data flow patterns.
    Provides both DTO-based methods (service layer) and model-based methods (database layer).
    """

    def __init__(self):
        self.openai_client = openai
        self.tokenizer = tokenizer
        self.db_manager = DatabaseManager()

    # DTO-based methods (Service Layer)
    def embed_chunk_dtos(self, chunk_dtos: List[ChunkDTO]) -> Dict[str, int]:
        """
        Embed a list of ChunkDTO objects (service layer method).
        Updates the DTOs in-place with embedding information.
        """
        stats = {
            'total_chunks': len(chunk_dtos),
            'embedded_successfully': 0,
            'embedding_failed': 0,
            'skipped_unchanged': 0
        }

        if not chunk_dtos:
            return stats

        try:
            # Process in batches
            for i in range(0, len(chunk_dtos), CHUNK_BATCH_SIZE):
                batch = chunk_dtos[i:i + CHUNK_BATCH_SIZE]
                batch_stats = self._embed_dto_batch(batch)

                # Aggregate stats
                for key in stats:
                    if key != 'total_chunks':
                        stats[key] += batch_stats.get(key, 0)

            return stats
        except Exception as e:
            logger.error(f"Error in embed_chunk_dtos: {e}")
            return stats

    def _embed_dto_batch(self, chunk_dtos: List[ChunkDTO]) -> Dict[str, int]:
        """Process a batch of ChunkDTO objects for embedding."""
        stats = {
            'embedded_successfully': 0,
            'embedding_failed': 0,
            'skipped_unchanged': 0
        }

        try:
            # Prepare texts and check for existing embeddings
            chunks_to_embed = []
            texts_to_embed = []

            for chunk_dto in chunk_dtos:
                prepared_text, text_hash = self._prepare_chunk_text_from_dto(chunk_dto)

                # Skip if already embedded with same hash
                if (chunk_dto.embedding_checksum == text_hash and
                    chunk_dto.embedding_vector is not None):
                    stats['skipped_unchanged'] += 1
                    continue

                chunks_to_embed.append((chunk_dto, text_hash))
                texts_to_embed.append(prepared_text)

            if not texts_to_embed:
                return stats

            # Create embeddings
            embeddings = self._create_embeddings_with_retry(texts_to_embed)
            current_time = datetime.utcnow()

            # Update DTOs with embeddings
            for (chunk_dto, text_hash), embedding in zip(chunks_to_embed, embeddings):
                chunk_dto.embedding_vector = embedding
                chunk_dto.embedding_checksum = text_hash
                chunk_dto.embedding_model = EMBEDDING_MODEL
                chunk_dto.embedding_ts = current_time
                stats['embedded_successfully'] += 1

            return stats
        except Exception as e:
            logger.error(f"Error in _embed_dto_batch: {e}")
            stats['embedding_failed'] = len(chunk_dtos) - stats['skipped_unchanged']
            return stats

    def _prepare_chunk_text_from_dto(self, chunk_dto: ChunkDTO) -> Tuple[str, str]:
        """Prepare chunk text from DTO with header and normalization."""
        # Generate structural header
        header = self._generate_structural_header_from_dto(chunk_dto)

        # Canonicalize numbers in chunk text
        normalized_text = self._canonicalize_numbers(chunk_dto.chunk_text)

        # Combine header and text
        full_text = f"{header}\n{normalized_text}"

        # Ensure token limit
        token_count = len(self.tokenizer.encode(full_text))
        if token_count > MAX_TOKENS_PER_CHUNK:
            header_tokens = len(self.tokenizer.encode(header + "\n"))
            max_content_tokens = MAX_TOKENS_PER_CHUNK - header_tokens
            if max_content_tokens > 0:
                trimmed_content = self._trim_text_to_token_limit(normalized_text, max_content_tokens)
                full_text = f"{header}\n{trimmed_content}"
            else:
                full_text = header

        # Generate SHA-256 hash
        text_hash = hashlib.sha256(full_text.encode('utf-8')).hexdigest()
        return full_text, text_hash

    def _generate_structural_header_from_dto(self, chunk_dto: ChunkDTO) -> str:
        """Generate structural header from ChunkDTO metadata."""
        header_parts = []
        metadata = chunk_dto.metadata_ or {}

        # Determine chunk type
        chunk_type = metadata.get('chunk_type', 'TEXT')

        # Add relevant metadata
        if chunk_dto.source_page_numbers:
            header_parts.append(f'pages={chunk_dto.source_page_numbers}')

        if chunk_dto.chunk_index is not None:
            header_parts.append(f'chunk={chunk_dto.chunk_index}')

        # Add structural metadata if available
        structural_meta = metadata.get('structural_metadata', {})
        if structural_meta.get('caption'):
            header_parts.append(f'caption="{structural_meta["caption"]}"')
        if structural_meta.get('section'):
            header_parts.append(f'section="{structural_meta["section"]}"')

        header = f"[{chunk_type.upper()}] " + " ".join(header_parts)
        return header

    # Model-based methods (Database Layer) - Keep existing functionality
    def embed_document_chunks(self, chunks: List[DocumentChunk]) -> Dict[str, int]:
        """
        Embed DocumentChunk models (database layer method).
        This is for direct database operations.
        """
        stats = {
            'total_chunks': len(chunks),
            'embedded_successfully': 0,
            'embedding_failed': 0
        }

        for chunk in chunks:
            try:
                success = self.embed_single_chunk(chunk)
                if success:
                    stats['embedded_successfully'] += 1
                else:
                    stats['embedding_failed'] += 1
            except Exception as e:
                logger.error(f"Error embedding chunk {chunk.chunk_id}: {e}")
                stats['embedding_failed'] += 1

        return stats

    # Summary chunks (works with dictionaries)
    def embed_summary_chunks(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Generate embeddings for a list of summary chunk dictionaries.
        This maintains compatibility with existing summary processing.
        """
        if not chunks:
            return []

        try:
            for i in range(0, len(chunks), CHUNK_BATCH_SIZE):
                batch = chunks[i:i + CHUNK_BATCH_SIZE]

                # Extract text from each chunk dictionary in the batch
                texts_to_embed = [c.get("text", "") for c in batch]

                # Filter out empty texts
                non_empty_texts = [text for text in texts_to_embed if text.strip()]

                if not non_empty_texts:
                    continue

                embeddings = self._create_embeddings_with_retry(non_empty_texts)

                # Assign embeddings back to the corresponding chunks
                embedding_index = 0
                for j, text in enumerate(texts_to_embed):
                    if text.strip():
                        batch[j]["embedding_vector"] = embeddings[embedding_index]
                        embedding_index += 1
                    else:
                        batch[j]["embedding_vector"] = None

            return chunks
        except Exception as e:
            logger.error(f"Error in embed_summary_chunks: {e}")
            return chunks

    def embed_single_chunk(self, chunk: DocumentChunk) -> bool:
        """
        Embed a single DocumentChunk model (database layer method).
        This function modifies the chunk object in-place with embedding data.

        TODO: DATATYPE ISSUES TO DISCUSS:
        - chunk.table_caption may not exist in metadata_list
        - page_number is in structural metadata, not directly on chunk
        - pptx files use slide_number instead of page_number
        - document.title may not exist in document type
        """
        try:
            document = self.db_manager.get_document_by_id(chunk.document_id)
            if not document:
                logger.warning(f"Document not found for document_id: {chunk.document_id}")
                return False

            prepared_text, text_hash = self._prepare_chunk_text_from_model(chunk, document)

            # Skip if already embedded with same hash
            if (chunk.embedding_checksum == text_hash and
                chunk.embedding_vector is not None):
                logger.debug(f"Chunk {chunk.chunk_id} already has current embedding")
                return True

            embeddings = self._create_embeddings_with_retry([prepared_text])

            # Update chunk with embedding data
            chunk.embedding_vector = embeddings[0]
            chunk.embedding_checksum = text_hash
            chunk.embedding_model = EMBEDDING_MODEL
            chunk.embedding_ts = datetime.utcnow()

            logger.debug(f"Successfully embedded chunk {chunk.chunk_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to embed chunk {chunk.chunk_id}: {e}")
            return False

    def embed_single_chunk_by_id(self, chunk_id: str) -> bool:
        """
        Embed a single chunk by ID - useful for testing or incremental updates.
        Returns True if successful, False otherwise.
        """
        try:
            chunk = self.db_manager.get_chunk_by_id(chunk_id)
            if not chunk:
                logger.warning(f"Chunk not found for chunk_id: {chunk_id}")
                return False

            return self.embed_single_chunk(chunk)
        except Exception as e:
            logger.error(f"Failed to embed chunk {chunk_id}: {e}")
            return False

    def embed_chunks_for_project(self, project_id: int) -> Dict[str, int]:
        """
        Enhanced embedding function for all chunks in a project.
        Returns statistics about the embedding process.

        TODO: PERFORMANCE CONSIDERATION - This processes all chunks at once.
        Consider adding pagination for large projects.
        """
        stats = {
            'total_chunks': 0,
            'skipped_unchanged': 0,
            'embedded_new': 0,
            'failed_chunks': 0,
            'batches_processed': 0
        }

        try:
            chunks = self.db_manager.get_project_document_chunks(project_id)
            documents = self.db_manager.get_project_documents(project_id)
            stats['total_chunks'] = len(chunks)

            if not chunks:
                return stats

            # Prepare chunks and check for changes
            chunks_to_embed = []
            current_time = datetime.utcnow()

            for chunk in chunks:
                document = documents.get(chunk.document_id)
                if not document:
                    stats['failed_chunks'] += 1
                    continue

                prepared_text, text_hash = self._prepare_chunk_text_from_model(chunk, document)

                # Skip if hash matches existing embedding
                if (chunk.embedding_checksum == text_hash and
                    chunk.embedding_vector is not None):
                    stats['skipped_unchanged'] += 1
                    continue

                chunks_to_embed.append((chunk, prepared_text, text_hash))

            if not chunks_to_embed:
                return stats

            # Create token-aware batches
            batches = self._create_token_aware_batches(chunks_to_embed)

            # Process each batch
            for batch in batches:
                try:
                    # Extract texts for embedding
                    texts = [text for _, text, _ in batch]

                    # Create embeddings with retry logic
                    embeddings = self._create_embeddings_with_retry(texts)

                    # Update database records
                    for (chunk, text, text_hash), embedding in zip(batch, embeddings):
                        chunk.embedding_vector = embedding
                        chunk.embedding_checksum = text_hash
                        chunk.embedding_model = EMBEDDING_MODEL
                        chunk.embedding_ts = current_time

                    stats['embedded_new'] += len(batch)
                    stats['batches_processed'] += 1

                except Exception as e:
                    logger.error(f"Failed to process batch: {e}")
                    stats['failed_chunks'] += len(batch)
                    continue

            return stats
        except Exception as e:
            logger.error(f"Error in embed_chunks_for_project: {e}")
            return stats

    def _prepare_chunk_text_from_model(self, chunk: DocumentChunk, document: Document) -> Tuple[str, str]:
        """
        Prepare chunk text from DocumentChunk model with header and normalization.

        TODO: DATATYPE ISSUES TO DISCUSS WITH DEVELOPERS:
        1. chunk.table_caption - may not exist in current schema
        2. chunk.page_number - should be in structural metadata
        3. document.title - may not exist in document model
        4. Need to handle slide_number for PPTX files
        """
        # Generate structural header
        header = self._generate_structural_header_from_model(chunk, document)

        # Get chunk text - TODO: Verify this attribute exists
        chunk_text = getattr(chunk, 'chunk_text', '') or getattr(chunk, 'text', '')

        # Canonicalize numbers in chunk text
        normalized_text = self._canonicalize_numbers(chunk_text)

        # Combine header and text
        full_text = f"{header}\n{normalized_text}"

        # Ensure token limit
        token_count = len(self.tokenizer.encode(full_text))
        if token_count > MAX_TOKENS_PER_CHUNK:
            header_tokens = len(self.tokenizer.encode(header + "\n"))
            max_content_tokens = MAX_TOKENS_PER_CHUNK - header_tokens
            if max_content_tokens > 0:
                trimmed_content = self._trim_text_to_token_limit(normalized_text, max_content_tokens)
                full_text = f"{header}\n{trimmed_content}"
            else:
                full_text = header

        # Generate SHA-256 hash
        text_hash = hashlib.sha256(full_text.encode('utf-8')).hexdigest()
        return full_text, text_hash

    def _generate_structural_header_from_model(self, chunk: DocumentChunk, document: Document) -> str:
        """
        Generate structural header from DocumentChunk model.

        TODO: CRITICAL DATATYPE ISSUES TO RESOLVE:
        1. table_caption attribute may not exist on chunk model
        2. page_number should come from structural metadata, not chunk directly
        3. For PPTX files, use slide_number instead of page_number
        4. document.title may not exist in document model
        5. Need to access structural metadata properly
        """
        header_parts = []

        # TODO: Fix this - table_caption may not exist
        # Check if chunk has table-related metadata
        if hasattr(chunk, 'table_caption') and chunk.table_caption:
            chunk_type = "TABLE"
            header_parts.append(f'caption="{chunk.table_caption}"')
            if hasattr(chunk, 'table_columns') and chunk.table_columns:
                header_parts.append(f'columns="{chunk.table_columns}"')
        # TODO: Fix this - page_number should be in structural metadata
        elif hasattr(chunk, 'page_number') and chunk.page_number:
            chunk_type = "PAGE"
            header_parts.append(f'page={chunk.page_number}')
        else:
            chunk_type = "TEXT"

        # TODO: Fix this - document.title may not exist
        # Add document-level metadata
        # if hasattr(document, 'title') and document.title:
        #     header_parts.append(f'doc_title="{document.title}"')

        # Add chunk position if available
        if hasattr(chunk, 'chunk_index') and chunk.chunk_index is not None:
            header_parts.append(f'chunk={chunk.chunk_index}')

        header = f"[{chunk_type}] " + " ".join(header_parts)
        return header

    def _create_token_aware_batches(self, prepared_chunks: List[Tuple[DocumentChunk, str, str]]) -> List[List[Tuple[DocumentChunk, str, str]]]:
        """
        Create batches based on token count rather than chunk count.
        Each batch should not exceed MAX_TOKENS_PER_BATCH tokens.
        """
        batches = []
        current_batch = []
        current_token_count = 0

        for chunk_data in prepared_chunks:
            chunk, text, text_hash = chunk_data
            text_tokens = len(self.tokenizer.encode(text))

            # If adding this chunk would exceed the limit, start a new batch
            if current_batch and current_token_count + text_tokens > MAX_TOKENS_PER_BATCH:
                batches.append(current_batch)
                current_batch = []
                current_token_count = 0

            current_batch.append(chunk_data)
            current_token_count += text_tokens

        # Add the last batch if it's not empty
        if current_batch:
            batches.append(current_batch)

        return batches

    # Utility methods
    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=2, min=2, max=32),
        retry=retry_if_exception_type((Exception,))
    )
    def _create_embeddings_with_retry(self, texts: List[str]) -> List[List[float]]:
        """Create embeddings with retry logic and exponential backoff."""
        response = self.openai_client.embeddings.create(
            input=texts,
            model=EMBEDDING_MODEL
        )
        return [embedding.embedding for embedding in response.data]

    def _canonicalize_numbers(self, text: str) -> str:
        """Convert various number formats to canonical form."""
        import re
        # Handle K/M/B suffixes with optional currency symbols
        text = re.sub(r'\$?(\d+(?:\.\d+)?)\s*K\b', lambda m: str(int(float(m.group(1)) * 1000)), text, flags=re.IGNORECASE)
        text = re.sub(r'\$?(\d+(?:\.\d+)?)\s*M\b', lambda m: str(int(float(m.group(1)) * 1000000)), text, flags=re.IGNORECASE)
        text = re.sub(r'\$?(\d+(?:\.\d+)?)\s*B\b', lambda m: str(int(float(m.group(1)) * 1000000000)), text, flags=re.IGNORECASE)
        # Remove commas from numbers
        text = re.sub(r'\b(\d+),(\d{3}(?:,\d{3})*)\b', lambda m: m.group(0).replace(',', ''), text)
        # Remove currency symbols for standalone numbers
        text = re.sub(r'\$(\d+(?:\.\d+)?)', r'\1', text)
        return text

    def _trim_text_to_token_limit(self, text: str, max_tokens: int) -> str:
        """Trim text to fit within token limit while preserving structure."""
        tokens = self.tokenizer.encode(text)
        if len(tokens) <= max_tokens:
            return text

        # Trim tokens and decode back to text
        trimmed_tokens = tokens[:max_tokens]
        trimmed_text = self.tokenizer.decode(trimmed_tokens)

        # Try to preserve sentence structure
        import re
        sentences = re.split(r'[.!?]+\s+', trimmed_text)
        if len(sentences) > 1:
            trimmed_text = '. '.join(sentences[:-1]) + '.'

        return trimmed_text
