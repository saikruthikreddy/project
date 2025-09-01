"""
Data models for document chunking.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import uuid

from sqlalchemy import DateTime

@dataclass
class ChunkMetadata:
    """Metadata structure for chunks"""
    # Required fields (no defaults) must come first

    # MISSING
    # text_chunk
    # extraction_method
    # token_count

    document_id: str
    project_id: str
    # Optional fields (with defaults) come after
    chunk_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_page_numbers: List[int] = field(default_factory=list)
    structural_metadata: Dict[str, Any] = field(default_factory=dict) # E.g. {"heading_level": 1, "is_table": True, "list_item": True}
    chunk_type: str = "unknown" # E.g. "prose", "table", "heading", "list_item", "code_block", "dialogue_turn"
    speaker_attribution: Optional[str] = None
    previous_chunk_id: Optional[str] = None
    same_table_group_id: Optional[str] = None
    chunk_index: Optional[int] = None  # Add chunk_index to metadata
    embedding_ts: DateTime = None

    # MISSING
    embedding_vector: List[float] = None
    embedding_model: str = None
    embedding_checksum: str = None
    slide_context_id: Optional[str] = None
    slide_number: Optional[int] = None
    semantic_similarity_score: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert the metadata to a dictionary."""
        return {
            "document_id": self.document_id,
            "project_id": self.project_id,
            "chunk_id": self.chunk_id,
            "source_page_numbers": self.source_page_numbers,
            "structural_metadata": self.structural_metadata,
            "chunk_type": self.chunk_type,
            "speaker_attribution": self.speaker_attribution,
            "semantic_similarity_score": self.semantic_similarity_score,
            "slide_number": self.slide_number,
            "previous_chunk_id": self.previous_chunk_id,
            "slide_context_id": self.slide_context_id,
            "same_table_group_id": self.same_table_group_id,
            "chunk_index": self.chunk_index,
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