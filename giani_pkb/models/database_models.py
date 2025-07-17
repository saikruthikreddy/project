import uuid

from typing import List
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, JSON, text, Index, Float
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
    source=Column(String(50), nullable=False)

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


    def to_dict(self):
        """Convert Document object to dictionary for JSON serialization."""
        return {
            'id': str(self.id),
            'original_filename': self.original_filename,
            'file_size': self.file_size,
            'file_mime_type': self.file_mime_type,
            'storage_path': self.storage_path,
            'category_folder': self.category_folder,
            'stored_filename': self.stored_filename,
            'source': self.source,
            'final_category': self.final_category,
            'final_purpose': self.final_purpose,
            'priority': self.priority,
            'text_preview': self.text_preview,
            'processed_content': self.processed_content,
            'extracted_text': self.extracted_text,
            'document_metadata': self.document_metadata,
            'summary_storage_path': self.summary_storage_path,
            'temp_file_path': self.temp_file_path,
            'date_added_to_giani': self.date_added_to_giani.isoformat() if self.date_added_to_giani else None,
            'finalized_at': self.finalized_at.isoformat() if self.finalized_at else None,
            'saved_at': self.saved_at.isoformat() if self.saved_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'user_id': str(self.user_id),
            'project_id': self.project_id
        }

class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    
    id = Column(Integer, primary_key=True, index=True)
    chunk_id = Column(String(100), unique=True, index=True, nullable=False)
    document_id = Column(String(36), ForeignKey("documents.id"), nullable=False)  # String, not UUID
    chunk_index = Column(Integer, nullable=True, default=0)
    chunk_text = Column(Text, nullable=False)
    source_page_number = Column(JSON)
    metadata_ = Column(JSON, default=dict)
    vector_id = Column(String(100))
    embedding_checksum = Column(String(64))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship("Document", back_populates="chunks")


class DocumentSummary(Base):
    """Model for storing document summaries generated by AI."""
    __tablename__ = "document_summaries"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True)
    
    # Core LLM Analysis - stores the complete structured response
    llm_analysis = Column(JSON, nullable=False)
    
    # Document context (extracted from summary_data)
    document_filename = Column(String(255))
    document_category = Column(String(100), index=True)
    document_group = Column(String(50), index=True)
    user_note_purpose = Column(Text)
    
    # Processing metadata
    processing_timestamp = Column(DateTime(timezone=True), server_default=func.now())
    llm_model_used = Column(String(100))  # Extracted from llm_analysis.llm_used_for_processing
    
    # File storage
    summary_storage_path = Column(String(500))  # Path to JSON file with full summary
    
    # Extracted fields for easy querying (denormalized from llm_analysis)
    narrative_summary = Column(Text)  # ai_high_level_narrative_summary
    key_themes = Column(JSON)  # ai_overall_key_themes_list
    key_takeaways = Column(JSON)  # ai_key_takeaways_bullets
    extracted_keywords = Column(JSON)  # extracted_keywords
    
    # Metadata for search and filtering
    document_sentiment = Column(String(20))  # from extracted_metadata.document_overall_sentiment
    suggested_title = Column(String(500))  # from extracted_metadata.suggested_document_title
    implied_audience = Column(String(200))  # from extracted_metadata.implied_audience
    geographical_focus = Column(String(200))  # from extracted_metadata.primary_geographical_focus
    
    # Key entities (for future search/filtering capabilities)
    key_people_mentioned = Column(JSON)  # from extracted_metadata.key_people_or_roles_mentioned
    key_organizations_mentioned = Column(JSON)  # from extracted_metadata.key_companies_organizations_mentioned
    key_dates_mentioned = Column(JSON)  # from extracted_metadata.key_dates_mentioned
    
    # Performance tracking
    processing_duration_seconds = Column(Float)
    
    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="summaries")
    
    # Indexes for common queries
    __table_args__ = (
        Index('idx_document_summary_doc_id', 'document_id'),
        Index('idx_document_summary_category', 'document_category'),
        Index('idx_document_summary_group', 'document_group'),
        Index('idx_document_summary_timestamp', 'processing_timestamp'),
        Index('idx_document_summary_sentiment', 'document_sentiment'),
    )
    
    def __repr__(self):
        return f"<DocumentSummary(id={self.id}, document_id={self.document_id}, category={self.document_category})>"
    
    @property
    def main_topics(self) -> list:
        """Extract main topics from llm_analysis."""
        if self.llm_analysis and 'ai_main_topics_with_summaries_list_of_objects' in self.llm_analysis:
            return self.llm_analysis['ai_main_topics_with_summaries_list_of_objects']
        return []
    
    @property
    def key_data_points(self) -> list:
        """Extract key data points from llm_analysis."""
        if (self.llm_analysis and 
            'extracted_metadata' in self.llm_analysis and 
            'rag_specific_metadata' in self.llm_analysis['extracted_metadata']):
            return self.llm_analysis['extracted_metadata']['rag_specific_metadata'].get('key_data_points_or_statistics_list', [])
        return []
    
    @property
    def key_recommendations(self) -> list:
        """Extract key recommendations from llm_analysis."""
        if (self.llm_analysis and 
            'extracted_metadata' in self.llm_analysis and 
            'cluster_a_specific_metadata' in self.llm_analysis['extracted_metadata']):
            return self.llm_analysis['extracted_metadata']['cluster_a_specific_metadata'].get('key_recommendations_or_proposals_list', [])
        return []


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
    source = Column(String(50), nullable=False)
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