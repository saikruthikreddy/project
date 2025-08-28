# File: services/rag/csv_index_builder.py

import pandas as pd
from typing import Optional
from llama_index.core import VectorStoreIndex
from services.rag.node_converter import convert_row_to_node

def build_index_from_csv(csv_path: str, project_id: int, document_content_type: Optional[str] = None) -> VectorStoreIndex:
    df = pd.read_csv(csv_path)

    # Filter based on project_id and doc type
    df = df[df["project_id"] == project_id]
    if document_content_type:
        df = df[df["document_content_type"] == document_content_type]

    nodes = [convert_row_to_node(row) for _, row in df.iterrows()]
    return VectorStoreIndex(nodes)