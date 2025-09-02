import uuid

from typing import List, Dict, Any
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, JSON, Index, Float
from sqlalchemy.orm import relationship, Mapped
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.types import TypeDecorator, TEXT
import json
from datetime import datetime, timezone

from utils.database import Base
class JSONEncodedList(TypeDecorator):
    """Represents a list structure as JSON-encoded string for SQLite compatibility."""

    impl = TEXT
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            value = json.dumps(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            value = json.loads(value)
        return value

class User(Base):
    """User model for authentication and user management."""
    __tablename__ = "users"
    __table_args__ = {'extend_existing': True}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    username = Column(String(50), nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=True)
    microsoft_id = Column(String, unique=True, nullable=True, index=True)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    projects: Mapped[List["Project"]] = relationship("Project", back_populates="owner")
    documents: Mapped[List["Document"]] = relationship("Document", back_populates="user")
    conversations: Mapped[List["Conversation"]] = relationship("Conversation", back_populates="user")

class Project(Base):
    """Project model for organizing documents and work."""
    __tablename__ = "projects"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    client_name = Column(Text)
    client_industry = Column(Text)
    target_audience = Column(Text)
    key_client_stakeholders_profiles = Column(Text)
    objectives = Column(Text)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    owner: Mapped["User"] = relationship("User", back_populates="projects")
    documents: Mapped[List["Document"]] = relationship("Document", back_populates="project")
    onboarding_guide: Mapped["OnboardingGuide"] = relationship("OnboardingGuide", back_populates="project", uselist=False, cascade="all, delete-orphan")
    conversations: Mapped[List["Conversation"]] = relationship("Conversation", back_populates="project")

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

class OnboardingGuide(Base):
    __tablename__ = "onboarding_guides"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, unique=True)
    content = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    project: Mapped["Project"] = relationship("Project", back_populates="onboarding_guide")

class Document(Base):
    """Document model for storing document metadata and information."""
    __tablename__ = "documents"
    __table_args__ = {'extend_existing': True}

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
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    chunk_id = Column(String(100), unique=True, index=True, nullable=False)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)  # String, not UUID
    chunk_index = Column(Integer, nullable=True, default=0)
    chunk_text = Column(Text, nullable=False)
    source_page_numbers = Column(JSON)
    metadata_ = Column(JSON, default=dict)
    vector_id = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    embedding_vector = Column(JSONEncodedList, nullable=True)
    embedding_model = Column(String(100), default="openai-embeddings")
    embedding_checksum = Column(String(64))
    embedding_ts = Column(DateTime(timezone=True))

    document: Mapped["Document"] = relationship("Document", back_populates="chunks")

    def to_dict(self, include_relationships: bool = False) -> Dict[str, Any]:
        """Convert model to dictionary"""
        result = {
            'id': self.id,
            'chunk_id': self.chunk_id,
            'document_id': str(self.document_id),
            'chunk_index': self.chunk_index,
            'chunk_text': self.chunk_text,
            'source_page_numbers': self.source_page_numbers,
            'metadata_': self.metadata_ or {},
            'vector_id': self.vector_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'embedding_vector': self.embedding_vector,
            'embedding_model': self.embedding_model,
            'embedding_checksum': self.embedding_checksum,
            'embedding_ts': self.embedding_ts.isoformat() if self.embedding_ts else None,
        }

        if include_relationships and self.document:
            try:
                result['document'] = self.document.to_dict() if hasattr(self.document, 'to_dict') else str(self.document)
            except:
                pass

        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DocumentChunk':
        """Create model instance from dictionary"""
        # Remove non-model fields
        model_data = {k: v for k, v in data.items()
                     if k in cls.__table__.columns.keys()}

        # Handle special conversions
        if 'document_id' in model_data and isinstance(model_data['document_id'], str):
            model_data['document_id'] = uuid.UUID(model_data['document_id'])

        if 'created_at' in model_data and isinstance(model_data['created_at'], str):
            model_data['created_at'] = datetime.fromisoformat(model_data['created_at'])

        if 'embedding_ts' in model_data and isinstance(model_data['embedding_ts'], str):
            model_data['embedding_ts'] = datetime.fromisoformat(model_data['embedding_ts'])

        return cls(**model_data)

    @classmethod
    def from_chunk_dto(cls, dto: 'ChunkDTO') -> 'DocumentChunk':
        """Create SQLAlchemy model from DTO"""
        return cls(
            chunk_id=dto.chunk_id,
            document_id=dto.document_id,
            chunk_index=dto.chunk_index,
            chunk_text=dto.chunk_text,
            source_page_numbers=dto.source_page_numbers,  # Note: field name diff
            metadata_=dto.metadata_,
            vector_id=dto.vector_id,
            embedding_vector=dto.embedding_vector,
            embedding_model=dto.embedding_model,
            embedding_checksum=dto.embedding_checksum,
            embedding_ts=dto.embedding_ts,
        )

    @staticmethod
    def to_dict_list(chunks: List['DocumentChunk'], include_relationships: bool = False) -> List[Dict[str, Any]]:
        """Convert list of models to list of dictionaries"""
        return [chunk.to_dict(include_relationships=include_relationships) for chunk in chunks]

    def __repr__(self):
        return f"<DocumentChunk(id={self.id}, chunk_id='{self.chunk_id}', document_id='{self.document_id}')>"

class DocumentSummary(Base):
    """Model for storing document summaries generated by AI."""
    __tablename__ = "document_summaries"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True)

    # Core LLM Analysis - stores both summarization and metadata responses
    summarization_analysis = Column(JSON, nullable=False)  # Contains summarization response
    metadata_analysis = Column(JSON, nullable=False)      # Contains metadata extraction response

    # Document context
    document_filename = Column(String(255))
    document_category = Column(String(100), index=True)
    document_group = Column(String(50), index=True)
    user_note_purpose = Column(Text)
    source = Column(String(50), nullable=False)

    # Processing metadata
    processing_timestamp = Column(DateTime(timezone=True), server_default=func.now())
    summarization_llm_model = Column(String(100))  # Model used for summarization
    metadata_llm_model = Column(String(100))       # Model used for metadata extraction

    # File storage
    summary_storage_path = Column(String(500))

    # Extracted fields for easy querying (from summarization_analysis)
    narrative_summary = Column(Text)           # ai_high_level_narrative_summary
    key_themes = Column(JSON)                  # ai_overall_key_themes_list
    key_takeaways = Column(JSON)               # ai_key_takeaways_bullets
    tldr_key_finding = Column(Text)            # ai_tldr_key_finding
    main_topics = Column(JSON)                 # ai_main_topics_with_summaries_list_of_objects

    # Extracted fields for easy querying (from metadata_analysis)
    extracted_keywords = Column(JSON)          # extracted_keywords
    document_sentiment = Column(String(20))    # from intelligence_layer analysis
    suggested_title = Column(String(500))      # from universal_metadata
    implied_audience = Column(String(200))     # from universal_metadata
    geographical_focus = Column(String(200))   # from universal_metadata

    # Intelligence layer data (from metadata_analysis)
    strategy_objectives = Column(JSON)         # strategy_and_objectives
    key_findings_data = Column(JSON)           # key_findings_and_data
    risks_mitigations = Column(JSON)           # risks_and_mitigations
    execution_actions = Column(JSON)           # execution_and_actions

    # RAG specific data
    potential_questions = Column(JSON)         # ai_generated_potential_questions_list

    # Key entities
    key_people_mentioned = Column(JSON)
    key_organizations_mentioned = Column(JSON)
    key_dates_mentioned = Column(JSON)

    # Performance tracking
    summarization_duration_seconds = Column(Float)
    metadata_duration_seconds = Column(Float)
    total_processing_duration_seconds = Column(Float)


    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="summaries")
    summary_chunks: Mapped[List["SummaryChunk"]] = relationship("SummaryChunk", back_populates="summary")

    def to_dict(self):
        """Convert DocumentSummary object to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'document_id': str(self.document_id),
            'summarization_analysis': self.summarization_analysis,
            'metadata_analysis': self.metadata_analysis,
            'document_filename': self.document_filename,
            'document_category': self.document_category,
            'document_group': self.document_group,
            'user_note_purpose': self.user_note_purpose,
            'source': self.source,
            'processing_timestamp': self.processing_timestamp.isoformat() if self.processing_timestamp else None,
            'summarization_llm_model': self.summarization_llm_model,
            'metadata_llm_model': self.metadata_llm_model,
            'summary_storage_path': self.summary_storage_path,

            # Denormalized fields from summarization_analysis
            'narrative_summary': self.narrative_summary,
            'key_themes': self.key_themes,
            'key_takeaways': self.key_takeaways,
            'tldr_key_finding': self.tldr_key_finding,
            'main_topics': self.main_topics,

            # Denormalized fields from metadata_analysis
            'extracted_keywords': self.extracted_keywords,
            'document_sentiment': self.document_sentiment,
            'suggested_title': self.suggested_title,
            'implied_audience': self.implied_audience,
            'geographical_focus': self.geographical_focus,

            # Intelligence layer data
            'strategy_objectives': self.strategy_objectives,
            'key_findings_data': self.key_findings_data,
            'risks_mitigations': self.risks_mitigations,
            'execution_actions': self.execution_actions,

            # RAG specific data
            'potential_questions': self.potential_questions,

            # Key entities
            'key_people_mentioned': self.key_people_mentioned,
            'key_organizations_mentioned': self.key_organizations_mentioned,
            'key_dates_mentioned': self.key_dates_mentioned,

            # Performance tracking
            'summarization_duration_seconds': self.summarization_duration_seconds,
            'metadata_duration_seconds': self.metadata_duration_seconds,
            'total_processing_duration_seconds': self.total_processing_duration_seconds
        }


class SummaryChunk(Base):
    """Model for storing specialized chunks derived from document summaries."""
    __tablename__ = "summary_chunks"

    id = Column(Integer, primary_key=True, index=True)
    chunk_id = Column(String(100), unique=True, index=True, nullable=False, default=lambda: str(uuid.uuid4()))
    summary_id = Column(Integer, ForeignKey("document_summaries.id"), nullable=False, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True)

    # Content and type
    chunk_text = Column(Text, nullable=False)
    chunk_type = Column(String(50), nullable=False, index=True)  # e.g., 'overall_summary', 'faq', 'entities'

    # Metadata
    metadata_ = Column(JSON, default=dict)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Vectorization info
    vector_id = Column(String(100), nullable=True)
    embedding_model = Column(String(100), default="openai-embeddings")
    embedding_vector = Column(JSONEncodedList, nullable=True)

    # Relationships
    summary: Mapped["DocumentSummary"] = relationship("DocumentSummary", back_populates="summary_chunks")
    document: Mapped["Document"] = relationship("Document")

    __table_args__ = (
        Index('idx_summary_chunk_summary_id_type', 'summary_id', 'chunk_type'),
    )


class APICallLog(Base):
    """Model for logging API calls for monitoring and debugging."""
    __tablename__ = "api_call_logs"
    __table_args__ = {'extend_existing': True}

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
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    temp_document_id = Column(String(100), unique=True, index=True, nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    source = Column(String(50), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=False)
    mime_type = Column(String(100), nullable=False)
    blob_name = Column(String(500), nullable=False, unique=True)
    upload_timestamp = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String(50), default="QUEUED_FOR_PRE_CLASSIFICATION")
    text_preview = Column(Text)

    # Relationships
    user: Mapped["User"] = relationship("User")
    project: Mapped["Project"] = relationship("Project")

class ProcessingBatch(Base):
    """Model for tracking batch document processing jobs."""
    __tablename__ = "processing_batches"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(String(100), unique=True, index=True, nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
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

class UserActivityLog(Base):
    """Model for tracking user activities and API usage."""
    __tablename__ = "user_activity_logs"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    session_id = Column(String(500), nullable=True, index=True)  # Track user sessions

    # Activity Details
    activity_type = Column(String(50), nullable=False, index=True)  # 'login', 'logout', 'api_call'
    endpoint = Column(String(200), nullable=True, index=True)
    http_method = Column(String(10), nullable=True)

    # Request Details
    user_agent = Column(String(500), nullable=True)
    client_type = Column(String(50), nullable=True)  # 'web', 'addin'
    ip_address = Column(String(45), nullable=True)

    # Response Details
    status_code = Column(Integer, nullable=True)
    response_time_ms = Column(Float, nullable=True)

    # Additional Context
    project_id = Column(Integer, nullable=True, index=True)
    feature_used = Column(String(100), nullable=True, index=True)
    additional_data = Column(JSON, nullable=True)

    # Timestamps
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Relationships
    user: Mapped["User"] = relationship("User")

    # Indexes for common queries
    __table_args__ = (
        Index('idx_user_activity_user_time', 'user_id', 'timestamp'),
        Index('idx_user_activity_type_time', 'activity_type', 'timestamp'),
        Index('idx_user_activity_endpoint', 'endpoint'),
        Index('idx_user_activity_feature', 'feature_used'),
    )

    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'user_id': str(self.user_id),
            'session_id': self.session_id,
            'activity_type': self.activity_type,
            'endpoint': self.endpoint,
            'http_method': self.http_method,
            'user_agent': self.user_agent,
            'client_type': self.client_type,
            'ip_address': self.ip_address,
            'status_code': self.status_code,
            'response_time_ms': self.response_time_ms,
            'project_id': self.project_id,
            'feature_used': self.feature_used,
            'additional_data': self.additional_data,
            'timestamp': self.timestamp.isoformat() if self.timestamp is not None else None
        }

class RefreshToken(Base):
    """Model for storing refresh tokens with rotation."""
    __tablename__ = "refresh_tokens"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    token_id = Column(String(64), unique=True, index=True, nullable=False)  # Opaque token
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    session_id = Column(String(64), ForeignKey("user_sessions.session_id"), nullable=False, index=True)

    # Token metadata
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used_at = Column(DateTime(timezone=True))

    # Security tracking
    client_type = Column(String(20))  # 'web', 'addin'
    user_agent = Column(String(500))
    ip_address = Column(String(45))

    # Status
    is_active = Column(Boolean, default=True, index=True)
    revoked_at = Column(DateTime(timezone=True))
    revoked_reason = Column(String(100))  # 'rotation', 'logout', 'suspicious'

    # Relationships
    user: Mapped["User"] = relationship("User")
    session: Mapped["UserSession"] = relationship("UserSession", back_populates="refresh_tokens")

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at

    def is_valid(self) -> bool:
        return self.is_active and not self.is_expired()

class UserSession(Base):
    """Model for tracking user sessions across devices/clients."""
    __tablename__ = "user_sessions"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(64), unique=True, index=True, nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    # Session metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_activity_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)

    # Client information
    client_type = Column(String(20))  # 'web', 'addin'
    user_agent = Column(String(500))
    ip_address = Column(String(45))
    device_fingerprint = Column(String(64))

    # Status
    is_active = Column(Boolean, default=True, index=True)
    ended_at = Column(DateTime(timezone=True))
    end_reason = Column(String(50))  # 'logout', 'timeout', 'security'

    # Relationships
    user: Mapped["User"] = relationship("User")
    refresh_tokens: Mapped[List["RefreshToken"]] = relationship("RefreshToken", back_populates="session")

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at

    def update_activity(self):
        self.last_activity_at = datetime.now(timezone.utc)

class Conversation(Base):
    """Model for storing conversations."""
    __tablename__ = "conversations"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    conversation_title = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="conversations")
    project: Mapped["Project"] = relationship("Project", back_populates="conversations")
    chat_messages: Mapped[List["ChatMessage"]] = relationship("ChatMessage", back_populates="conversation", cascade="all, delete-orphan")

class ChatMessage(Base):
    """Model for storing chat messages."""
    __tablename__ = "chat_messages"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, nullable=False)
    conversation_id = Column(UUID(as_uuid=True),ForeignKey("conversations.conversation_id"),nullable=False,index=True)
    message = Column(Text, nullable=False)
    sender_type = Column(String(50), nullable=False)  # "human" or "AI"
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="chat_messages")
