import uuid

from typing import List
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, JSON
from sqlalchemy.orm import relationship, Mapped
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
from giani_pkb.utils.database import Base

class User(Base):
    """User model for authentication and user management."""
    __tablename__ = "users"

    # id = Column(Integer, primary_key=True, index=True)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    projects: Mapped[List["Project"]] = relationship("Project", back_populates="owner")
    documents: Mapped[List["Document"]] = relationship("Document", back_populates="user")

class Project(Base):
    """Project model for organizing documents and work."""
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    client_name = Column(Text)
    client_industry = Column(Text)
    target_audience = Column(Text)
    key_client_stakeholders_profiles = Column(Text)
    objectives = Column(Text)
    # owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    owner: Mapped["User"] = relationship("User", back_populates="projects")
    documents: Mapped[List["Document"]] = relationship("Document", back_populates="project")

    def to_dict(self):
        """Convert project to dictionary for JSON serialization."""
        return {
            'id': str(self.id),  # Convert UUID to string
            'name': self.name,
            'description': self.description,
            'owner_id': str(self.owner_id),  # Convert UUID to string
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if hasattr(self, 'created_at') and self.created_at else None,
            'updated_at': self.updated_at.isoformat() if hasattr(self, 'updated_at') and self.updated_at else None,
        }
    
    def to_dict_detailed(self):
        """Convert project to dictionary for JSON serialization."""
        return {
            'id': str(self.id),  # Convert to string for consistency
            'name': self.name,
            'description': self.description,
            'client_name': self.client_name,
            'client_industry': self.client_industry,
            'target_audience': self.target_audience,
            'key_client_stakeholders_profiles': self.key_client_stakeholders_profiles,
            'objectives': self.objectives,
            'owner_id': str(self.owner_id),  # Convert UUID to string
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if hasattr(self, 'created_at') and self.created_at else None,
            'updated_at': self.updated_at.isoformat() if hasattr(self, 'updated_at') and self.updated_at else None,
        }

class Document(Base):
    """Document model for storing document metadata and information."""
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_size = Column(Integer, nullable=False)
    file_mime_type = Column(String(100), nullable=False)
    storage_path = Column(String(500), nullable=False)
    category_folder = Column(String(100), nullable=False)
    stored_filename = Column(String(500), nullable=False)

    # AI Classification fields
    final_category = Column(String(100), nullable=False)
    final_purpose = Column(Text, nullable=False)
    priority = Column(String(20), default="Medium")

    # Content fields
    text_preview = Column(Text)
    processed_content = Column(Text)
    extracted_text = Column(Text)

    # Metadata
    document_metadata = Column(JSON, default=dict)
    summary_storage_path = Column(String(500))
    temp_file_path = Column(String(500))

    # Timestamps
    date_added_to_giani = Column(DateTime(timezone=True), server_default=func.now())
    finalized_at = Column(DateTime(timezone=True), server_default=func.now())
    saved_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Foreign keys
    # user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="documents")
    project: Mapped["Project"] = relationship("Project", back_populates="documents")
    chunks: Mapped[List["DocumentChunk"]] = relationship("DocumentChunk", back_populates="document")
    summaries: Mapped[List["DocumentSummary"]] = relationship("DocumentSummary", back_populates="document")

class DocumentChunk(Base):
    """Model for storing document chunks for processing and analysis."""
    __tablename__ = "document_chunks"
    
    id = Column(Integer, primary_key=True, index=True)
    chunk_id = Column(String(100), unique=True, index=True, nullable=False)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    chunk_index = Column(Integer, nullable=True, default=0)
    chunk_text = Column(Text, nullable=False)  # Changed from chunk_text_content
    source_page_number = Column(JSON)
    metadata_ = Column(JSON, default=dict)  # Changed from structural_metadata
    vector_id = Column(String(100))
    embedding_checksum = Column(String(64))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="chunks")

class DocumentSummary(Base):
    """Model for storing document summaries generated by AI."""
    __tablename__ = "document_summaries"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    summary_content = Column(Text, nullable=False)
    llm_used = Column(String(100), nullable=False)
    processing_timestamp = Column(DateTime(timezone=True), server_default=func.now())
    summary_metadata = Column(JSON, default=dict)
    storage_path = Column(String(500))

    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="summaries")

class APICallLog(Base):
    """Model for logging API calls for monitoring and debugging."""
    __tablename__ = "api_call_logs"

    id = Column(Integer, primary_key=True, index=True)
    call_number = Column(Integer, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    model = Column(String(100), nullable=False)
    prompt_preview = Column(Text)
    response_preview = Column(Text)
    prompt_length = Column(Integer)
    response_length = Column(Integer)
    success = Column(Boolean, default=True)
    error_message = Column(Text)

    # Store full content as JSON for debugging
    full_prompt = Column(Text)
    full_response = Column(Text)

class TempDocument(Base):
    """Model for staging uploaded documents before finalization."""
    __tablename__ = "temp_documents"

    id = Column(Integer, primary_key=True, index=True)
    temp_document_id = Column(String(100), unique=True, index=True, nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    # user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    original_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=False)
    mime_type = Column(String(100), nullable=False)
    upload_timestamp = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String(50), default="QUEUED_FOR_PRE_CLASSIFICATION")
    text_preview = Column(Text)

    # Relationships
    user: Mapped["User"] = relationship("User")
    project: Mapped["Project"] = relationship("Project")

class ProcessingBatch(Base):
    """Model for tracking batch document processing jobs."""
    __tablename__ = "processing_batches"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(String(100), unique=True, index=True, nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    # user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    status = Column(String(50), default="QUEUED")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    total_documents = Column(Integer, default=0)
    processed_documents = Column(Integer, default=0)
    failed_documents = Column(Integer, default=0)
    error_details = Column(Text)

    # Relationships
    user: Mapped["User"] = relationship("User")
    project: Mapped["Project"] = relationship("Project")