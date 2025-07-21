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
