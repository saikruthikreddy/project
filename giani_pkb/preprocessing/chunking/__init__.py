"""
Document chunking package for Giani AI.

This package provides various strategies for chunking documents into smaller,
manageable pieces for processing and analysis.
"""

from .models import ChunkMetadata
from .token_counter import TokenCounter
from .nlp_processor import NLPProcessor
from .strategies import (
    chunk_formal_document,
    chunk_conversational_record,
    chunk_data_heavy_document,
    chunk_document_semantic,
    chunk_document_adaptive
)

__all__ = [
    'ChunkMetadata',
    'TokenCounter',
    'NLPProcessor',
    'chunk_formal_document',
    'chunk_conversational_record',
    'chunk_data_heavy_document',
    'chunk_document_semantic',
    'chunk_document_adaptive'
]