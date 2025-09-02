"""
Data models for document chunking.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import uuid

from sqlalchemy import DateTime

@dataclass
class ChunkMetadata:
    """Metadata structure for chunks - matches what's actually used in strategies.py"""
    # Required fields (no defaults) must come first
    document_id: str
    project_id: str

    # Core chunk fields (actually used in strategies.py)
    chunk_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    chunk_index: Optional[int] = None
    chunk_type: str = "unknown"  # E.g. "prose", "table", "heading", "list_item", "code_block", "dialogue_turn", "metric"

    # Page/slide information (actually used)
    source_page_numbers: List[int] = field(default_factory=list)
    slide_number: Optional[int] = None

    # Chunk relationships (actually used)
    previous_chunk_id: Optional[str] = None
    same_table_group_id: Optional[str] = None
    slide_context_id: Optional[str] = None

    # Content-specific metadata (actually used)
    speaker_attribution: Optional[str] = None
    semantic_similarity_score: Optional[float] = None

    # Structural metadata (comprehensive dict - this is where most data goes)
    structural_metadata: Dict[str, Any] = field(default_factory=dict)

    # Embedding information (added during embedding process)
    embedding_vector: Optional[List[float]] = None
    embedding_model: Optional[str] = None
    embedding_checksum: Optional[str] = None
    embedding_ts: Optional[DateTime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert the metadata to a dictionary."""
        return {
            # Core fields
            "document_id": self.document_id,
            "project_id": self.project_id,
            "chunk_id": self.chunk_id,
            "chunk_index": self.chunk_index,
            "chunk_type": self.chunk_type,

            # Page/slide information
            "source_page_numbers": self.source_page_numbers,
            "slide_number": self.slide_number,

            # Chunk relationships
            "previous_chunk_id": self.previous_chunk_id,
            "same_table_group_id": self.same_table_group_id,
            "slide_context_id": self.slide_context_id,

            # Content-specific metadata
            "speaker_attribution": self.speaker_attribution,
            "semantic_similarity_score": self.semantic_similarity_score,

            # Structural metadata (this contains most of the detailed info)
            "structural_metadata": self.structural_metadata,

            # Embedding information
            "embedding_vector": self.embedding_vector,
            "embedding_model": self.embedding_model,
            "embedding_checksum": self.embedding_checksum,
            "embedding_ts": self.embedding_ts.isoformat() if self.embedding_ts else None,
        }


# STRUCTURAL METADATA (From Kruthik's list)

# character_count: int
# Xbox_units: int
# original_block_type: str
# original_file_name: str
# section_type: str

# bbox: list
# block_type: str
# caption: str
# column_headers: list
# column_names: list
# current_heading_text: str
# filename: str
# heading_context: str
# page_number: int
# region_id: str
# region_type: str
# section_heading: str
# section_id: int
# sheet_name: str
# slide_number: int
# source: str
# source_type: str
# word_count: int