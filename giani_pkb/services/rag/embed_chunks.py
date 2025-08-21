# File: giani_pkb/utils/embed_chunks.py
from openai import OpenAI
from sqlalchemy.orm import Session
from giani_pkb.models.database_models import DocumentChunk, Document
from giani_pkb.utils.config import config

openai = OpenAI(api_key=config.OPENAI_API_KEY)

def embed_chunks_for_project(db: Session, project_id: int):
    documents = db.query(Document).filter(
        Document.project_id == project_id).all()
    document_ids = [d.id for d in documents]
    if not document_ids:
        return

    CHUNK_BATCH = 96
    chunks = (db.query(DocumentChunk)
                .filter(DocumentChunk.document_id.in_(document_ids))
                .filter(DocumentChunk.embedding_vector.is_(None))
                .all())

    for i in range(0, len(chunks), CHUNK_BATCH):
        batch = chunks[i:i+CHUNK_BATCH]
        resp = openai.embeddings.create(
            input=[c.chunk_text for c in batch],
            model="text-embedding-ada-002")
        for ch, emb in zip(batch, resp.data):
            ch.embedding_vector = emb.embedding
    db.commit()


def embed_summary_chunks(chunks: list) -> list:
    """
    Generate embeddings for a list of summary chunks.
    """
    if not chunks:
        return []

    CHUNK_BATCH = 96
    for i in range(0, len(chunks), CHUNK_BATCH):
        batch = chunks[i:i+CHUNK_BATCH]
        
        # Extract text from each chunk dictionary in the batch
        texts_to_embed = [c.get("text", "") for c in batch]
        
        # Filter out empty texts to avoid errors with the embedding API
        non_empty_texts = [text for text in texts_to_embed if text.strip()]
        
        if not non_empty_texts:
            continue

        resp = openai.embeddings.create(
            input=non_empty_texts,
            model="text-embedding-ada-002"
        )
        
        # Assign embeddings back to the corresponding chunks
        embedding_index = 0
        for j, text in enumerate(texts_to_embed):
            if text.strip():
                batch[j]["embedding_vector"] = resp.data[embedding_index].embedding
                embedding_index += 1
            else:
                batch[j]["embedding_vector"] = None

    return chunks
