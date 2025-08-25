import re
import hashlib
import tiktoken
from datetime import datetime
from typing import List, Tuple, Optional
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from openai import OpenAI
from sqlalchemy.orm import Session
from giani_pkb.models.database_models import DocumentChunk, Document
from giani_pkb.utils.config import config
# Initialize OpenAI client and tokenizer
openai = OpenAI(api_key=config.OPENAI_API_KEY)
tokenizer = tiktoken.encoding_for_model("text-embedding-3-small")
# Constants
EMBEDDING_MODEL = "text-embedding-3-small"
MAX_TOKENS_PER_CHUNK = 7500
MAX_TOKENS_PER_BATCH = 100000
MAX_RETRIES = 5
def canonicalize_numbers(text: str) -> str:
    """
    Convert various number formats to canonical form:
    - 12K → 12000
    - $3.5M → 3500000
    - 10,000 → 10000
    """
    # Handle K/M/B suffixes with optional currency symbols
    text = re.sub(r'\$?(\d+(?:\.\d+)?)\s*K\b', lambda m: str(int(float(m.group(1)) * 1000)), text, flags=re.IGNORECASE)
    text = re.sub(r'\$?(\d+(?:\.\d+)?)\s*M\b', lambda m: str(int(float(m.group(1)) * 1000000)), text, flags=re.IGNORECASE)
    text = re.sub(r'\$?(\d+(?:\.\d+)?)\s*B\b', lambda m: str(int(float(m.group(1)) * 1000000000)), text, flags=re.IGNORECASE)
    # Remove commas from numbers
    text = re.sub(r'\b(\d+),(\d{3}(?:,\d{3})*)\b', lambda m: m.group(0).replace(',', ''), text)
    # Remove currency symbols for standalone numbers
    text = re.sub(r'\$(\d+(?:\.\d+)?)', r'\1', text)
    return text
def generate_structural_header(chunk: DocumentChunk, document: Document) -> str:
    """
    Generate a structural header for the chunk based on available metadata.
    Format: [TYPE] key1=value1 key2=value2
    """
    header_parts = []
    # Determine chunk type based on available metadata
    if hasattr(chunk, 'table_caption') and chunk.table_caption:
        chunk_type = "TABLE"
        header_parts.append(f'caption="{chunk.table_caption}"')
        if hasattr(chunk, 'table_columns') and chunk.table_columns:
            header_parts.append(f'columns="{chunk.table_columns}"')
    elif hasattr(chunk, 'page_number') and chunk.page_number:
        chunk_type = "PAGE"
        header_parts.append(f'page={chunk.page_number}')
    else:
        chunk_type = "TEXT"
    # Add document-level metadata
    if document.title:
        header_parts.append(f'doc_title="{document.title}"')
    # Add chunk position if available
    if hasattr(chunk, 'chunk_index') and chunk.chunk_index is not None:
        header_parts.append(f'chunk={chunk.chunk_index}')
    header = f"[{chunk_type}] " + " ".join(header_parts)
    return header
def trim_text_to_token_limit(text: str, max_tokens: int) -> str:
    """
    Trim text to fit within token limit while preserving structure.
    """
    tokens = tokenizer.encode(text)
    if len(tokens) <= max_tokens:
        return text
    # Trim tokens and decode back to text
    trimmed_tokens = tokens[:max_tokens]
    trimmed_text = tokenizer.decode(trimmed_tokens)
    # Try to preserve sentence structure by finding last complete sentence
    sentences = re.split(r'[.!?]+\s+', trimmed_text)
    if len(sentences) > 1:
        # Remove the last (potentially incomplete) sentence
        trimmed_text = '. '.join(sentences[:-1]) + '.'
    return trimmed_text
def prepare_chunk_text(chunk: DocumentChunk, document: Document) -> Tuple[str, str]:
    """
    Prepare chunk text with header and normalization.
    Returns: (prepared_text, sha256_hash)
    """
    # Generate structural header
    header = generate_structural_header(chunk, document)
    # Canonicalize numbers in chunk text
    normalized_text = canonicalize_numbers(chunk.chunk_text)
    # Combine header and text
    full_text = f"{header}\n{normalized_text}"
    # Ensure token limit
    token_count = len(tokenizer.encode(full_text))
    if token_count > MAX_TOKENS_PER_CHUNK:
        # Calculate how many tokens we need to remove
        excess_tokens = token_count - MAX_TOKENS_PER_CHUNK
        header_tokens = len(tokenizer.encode(header + "\n"))
        max_content_tokens = MAX_TOKENS_PER_CHUNK - header_tokens
        if max_content_tokens > 0:
            trimmed_content = trim_text_to_token_limit(normalized_text, max_content_tokens)
            full_text = f"{header}\n{trimmed_content}"
        else:
            # If header is too long, just use the header
            full_text = header
    # Generate SHA-256 hash
    text_hash = hashlib.sha256(full_text.encode('utf-8')).hexdigest()
    return full_text, text_hash
def create_token_aware_batches(prepared_chunks: List[Tuple[DocumentChunk, str, str]]) -> List[List[Tuple[DocumentChunk, str, str]]]:
    """
    Create batches based on token count rather than chunk count.
    Each batch should not exceed MAX_TOKENS_PER_BATCH tokens.
    """
    batches = []
    current_batch = []
    current_token_count = 0
    for chunk_data in prepared_chunks:
        chunk, text, text_hash = chunk_data
        text_tokens = len(tokenizer.encode(text))
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
@retry(
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential(multiplier=2, min=2, max=32),
    retry=retry_if_exception_type((Exception,))  # You might want to be more specific about which exceptions to retry
)
def create_embeddings_with_retry(texts: List[str]) -> List[List[float]]:
    """
    Create embeddings with retry logic and exponential backoff.
    """
    response = openai.embeddings.create(
        input=texts,
        model=EMBEDDING_MODEL
    )
    return [embedding.embedding for embedding in response.data]
def embed_chunks_for_project(db: Session, project_id: int) -> dict:
    """
    Enhanced embedding function with all improvements applied.
    Returns statistics about the embedding process.
    """
    stats = {
        'total_chunks': 0,
        'skipped_unchanged': 0,
        'embedded_new': 0,
        'failed_chunks': 0,
        'batches_processed': 0
    }
    # Get documents for the project
    documents = db.query(Document).filter(Document.project_id == project_id).all()
    if not documents:
        return stats
    document_dict = {doc.id: doc for doc in documents}
    document_ids = list(document_dict.keys())
    # Get chunks that need embedding (no embedding_vector OR outdated hash)
    chunks = (db.query(DocumentChunk)
              .filter(DocumentChunk.document_id.in_(document_ids))
              .all())
    stats['total_chunks'] = len(chunks)
    if not chunks:
        return stats
    # Prepare chunks and check for changes
    chunks_to_embed = []
    current_time = datetime.utcnow()
    for chunk in chunks:
        document = document_dict[chunk.document_id]
        prepared_text, text_hash = prepare_chunk_text(chunk, document)
        # Skip if hash matches existing embedding
        if (hasattr(chunk, 'embedding_hash') and
            chunk.embedding_hash == text_hash and
            chunk.embedding_vector is not None):
            stats['skipped_unchanged'] += 1
            continue
        chunks_to_embed.append((chunk, prepared_text, text_hash))
    if not chunks_to_embed:
        return stats
    # Create token-aware batches
    batches = create_token_aware_batches(chunks_to_embed)
    # Process each batch
    for batch in batches:
        try:
            # Extract texts for embedding
            texts = [text for _, text, _ in batch]
            # Create embeddings with retry logic
            embeddings = create_embeddings_with_retry(texts)
            # Update database records
            for (chunk, text, text_hash), embedding in zip(batch, embeddings):
                chunk.embedding_vector = embedding
                chunk.embedding_hash = text_hash
                chunk.embedding_model = EMBEDDING_MODEL
                chunk.embedding_ts = current_time
            stats['embedded_new'] += len(batch)
            stats['batches_processed'] += 1
        except Exception as e:
            print(f"Failed to process batch: {e}")
            stats['failed_chunks'] += len(batch)
            continue
    # Commit all changes
    try:
        db.commit()
    except Exception as e:
        print(f"Failed to commit changes: {e}")
        db.rollback()
        raise
    return stats
def embed_single_chunk(db: Session, chunk_id: int) -> bool:
    """
    Embed a single chunk - useful for testing or incremental updates.
    Returns True if successful, False otherwise.
    """
    chunk = db.query(DocumentChunk).filter(DocumentChunk.id == chunk_id).first()
    if not chunk:
        return False
    document = db.query(Document).filter(Document.id == chunk.document_id).first()
    if not document:
        return False
    try:
        prepared_text, text_hash = prepare_chunk_text(chunk, document)
        # Skip if already embedded with same hash
        if (hasattr(chunk, 'embedding_hash') and
            chunk.embedding_hash == text_hash and
            chunk.embedding_vector is not None):
            return True
        embeddings = create_embeddings_with_retry([prepared_text])
        chunk.embedding_vector = embeddings[0]
        chunk.embedding_hash = text_hash
        chunk.embedding_model = EMBEDDING_MODEL
        chunk.embedding_ts = datetime.utcnow()
        db.commit()
        return True
    except Exception as e:
        print(f"Failed to embed chunk {chunk_id}: {e}")
        db.rollback()
        return False