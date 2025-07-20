# File: giani_pkb/utils/embed_chunks.py
from openai import OpenAI
from sqlalchemy.orm import Session
from giani_pkb.models.database_models import DocumentChunk
from giani_pkb.utils.config import OPENAI_API_KEY

openai = OpenAI(api_key=OPENAI_API_KEY)

def embed_chunks_for_project(db: Session, project_id: int):
    chunks = db.query(DocumentChunk).filter(DocumentChunk.project_id == project_id).all()
    for chunk in chunks:
        if not chunk.embedding_vector:  # Skip if already embedded
            response = openai.embeddings.create(
                input=chunk.chunk_text_content,
                model="text-embedding-ada-002"
            )
            chunk.embedding_vector = response.data[0].embedding
    db.commit()