"""
Data models for document chunking.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import uuid

@dataclass
class ChunkMetadata:
    """Metadata structure for chunks"""
    # Required fields (no defaults) must come first
    document_id: str
    project_id: str

    # Optional fields (with defaults) come after
    chunk_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_page_numbers: List[int] = field(default_factory=list)
    structural_metadata: Dict[str, Any] = field(default_factory=dict) # E.g. {"heading_level": 1, "is_table": True, "list_item": True}
    chunk_type: str = "unknown" # E.g. "prose", "table", "heading", "list_item", "code_block", "dialogue_turn"
    speaker_attribution: Optional[str] = None
    semantic_similarity_score: Optional[float] = None
    slide_number: Optional[int] = None
    previous_chunk_id: Optional[str] = None
    slide_context_id: Optional[str] = None
    same_table_group_id: Optional[str] = None