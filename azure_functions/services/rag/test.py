# test.py - FINAL VERSION WITH DEBUG FIXES

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
import pandas as pd

# --- Project imports ---
from azure_functions.services.rag.planner import route_and_plan, QueryPlan
from azure_functions.services.rag.config_loader import load_orchestration_config
from azure_functions.services.rag.retrieval_service import UnifiedRetrievalService
from azure_functions.services.rag.fusion import FusionEngine

# --- LlamaIndex imports ---
from llama_index.core import VectorStoreIndex
from llama_index.core.schema import TextNode
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

# ==============================================================
# Configuration
# ==============================================================
DEFAULT_OUT_DIR: str = "rag_output"

from dotenv import load_dotenv
load_dotenv()

# ==============================================================
# Utilities
# ==============================================================

def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def _source_title(meta: Dict[str, Any]) -> str:
    return meta.get("heading_context") or meta.get("section_heading") or f"Slide {meta.get('slide_number')}" or "untitled"

def _serialize_node_with_score(n) -> Dict[str, Any]:
    meta = getattr(n.node, "metadata", {}) or {}
    return {
        "id": getattr(n.node, "id_", None),
        "chunk_id": getattr(n.node, "id_", None),
        "score": float(n.score) if n.score is not None else None,
        "rrf_score": float(n.score) if n.score is not None else None,
        "title": _source_title(meta),
        "text": getattr(n.node, "text", ""),
        "metadata": _make_json_serializable(meta),
    }

def _serialize_chunk(c) -> Dict[str, Any]:
    meta = getattr(c, "metadata", {}) or {}
    return {
        "id": getattr(c, "id_", None),
        "chunk_id": getattr(c, "id_", None),
        "title": _source_title(meta),
        "metadata": _make_json_serializable(meta),
        "text": getattr(c, "text", None) or getattr(c, "get_content", lambda: "")(),
    }

def _make_json_serializable(obj: Any) -> Any:
    import numpy as np
    if isinstance(obj, dict):
        return {k: _make_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_make_json_serializable(item) for item in obj]
    return obj

# ==============================================================
# Dummy Fetcher & Tracing Schema
# ==============================================================

def fetch_sources_by_ids(source_ids: List[str]) -> List[Dict[str, Any]]:
    return []

@dataclass
class SubqueryTrace:
    subquery: str
    success: bool
    num_results: int
    results: List[Dict[str, Any]]

@dataclass
class RunTrace:
    run_id: str
    query: str
    subqueries: List[str]
    per_subquery: List[SubqueryTrace]
    fusion: Dict[str, Any]
    answer: Dict[str, Any]

# ==============================================================
# Answer Synthesis
# ==============================================================

def synthesize_answer_from_chunks(chunks: List[Any], max_chars: int = 800) -> str:
    parts: List[str] = []
    for c in chunks[:4]: # Use top 4 chunks for answer
        text = (c.get("text", "") or c.get("content", "")).strip()
        if text:
            parts.append(text)
    if not parts:
        return "No supporting context could be found to generate an answer."
    ans = "\n\n".join(parts)
    return ans[:max_chars].rstrip() + ("…" if len(ans) > max_chars else "")


# ==============================================================
# Index Builder for Pre-Chunked Data
# ==============================================================

def build_index_from_prechunked_json(json_file_path: str) -> VectorStoreIndex:
    """
    Builds a VectorStoreIndex directly from your pre-chunked JSON file.
    Supports both formats:
      - [ {chunk}, {chunk}, ... ]
      - { "summary": {...}, "chunks": [ {chunk}, {chunk}, ... ] }
    """
    print(f"--- Loading pre-computed chunks from {json_file_path} ---")
    with open(json_file_path, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)

    # Detect format
    if isinstance(raw_data, dict):
        chunks_data = raw_data.get("chunks", [])
    elif isinstance(raw_data, list):
        chunks_data = raw_data
    else:
        raise ValueError("Unsupported JSON structure for pre-chunked data")

    print(f"--- Loaded {len(chunks_data)} chunks ---")

    print("--- Converting chunks to LlamaIndex TextNodes ---")
    text_nodes: List[TextNode] = []
    for chunk_dict in chunks_data:
        if not isinstance(chunk_dict, dict):
            continue  # skip invalid entries

        node = TextNode(
            text=chunk_dict.get("text_chunk", ""),
            id_=chunk_dict.get("metadata", {}).get("chunk_id", str(uuid.uuid4())),
            metadata=chunk_dict.get("metadata", {})
        )
        text_nodes.append(node)

    print(f"--- Created {len(text_nodes)} TextNodes ---")

    print("--- Building VectorStoreIndex from pre-chunked nodes ---")
    embed_model = HuggingFaceEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")
    index = VectorStoreIndex(nodes=text_nodes, embed_model=embed_model)
    
    print(f"--- Index built successfully with {len(index.docstore.docs)} nodes! ---")
    return index



# ==============================================================
# Main Function
# ==============================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive RAG test with pre-chunked data.")
    parser.add_argument(
        "--chunk_file",
        type=str,
        required=True,
        help="Path to the JSON file containing your pre-chunked data.",
    )
    parser.add_argument(
        "--out_dir",
        type=str,
        default=DEFAULT_OUT_DIR,
        help=f"Directory to store run traces (default: {DEFAULT_OUT_DIR}).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    structlog.configure(processors=[structlog.processors.JSONRenderer()])
    log = structlog.get_logger("interactive")

    config = load_orchestration_config()

    # Build the index using your pre-chunked data file
    index = build_index_from_prechunked_json(args.chunk_file)

    # ADD DEBUG LOGGING HERE
    print(f"\n🔍 DEBUG: Index contains {len(index.docstore.docs)} documents")
    print("🔍 DEBUG: Sample document IDs and content:")
    for i, (doc_id, doc) in enumerate(list(index.docstore.docs.items())[:3]):
        print(f"   {i+1}. ID: {doc_id}")
        print(f"      Text preview: {doc.text[:100]}...")
        print(f"      Metadata: {doc.metadata}")
    
    # Test a simple query directly on the index
    print("\n🔍 DEBUG: Testing direct index query...")
    try:
        retriever = index.as_retriever(similarity_top_k=5)
        test_results = retriever.retrieve("test query")
        print(f"   Direct retrieval returned {len(test_results)} results")
        for i, result in enumerate(test_results[:2]):
            print(f"   {i+1}. Score: {result.score:.4f}, Text: {result.text[:50]}...")
    except Exception as e:
        print(f"   Direct retrieval failed: {e}")

    service = UnifiedRetrievalService(primary_index=index, secondary_index=None)

    try:
        user_q = input("\n🔎 Enter your query: ").strip()
    except EOFError:
        user_q = ""

    if not user_q:
        print("No query entered. Exiting.")
        return 0

    # --- INTEGRATING THE REAL PLANNER ---
    # Generate the run_id now so we can use it for both planning and tracing
    run_id = f"run-{uuid.uuid4()}"

    print("\n🧩 Planning query with intelligent router...")
    try:
        # Call your real async planner function from planner.py
        plan: QueryPlan = asyncio.run(
            route_and_plan(
                query=user_q,
                user_context={"project_id": "proj_test_456"}, # Use the project_id from your chunks
                query_id=run_id
            )
        )
        # Extract the subquery texts from the plan object
        subqueries = [sq['text'] for sq in plan.subqueries]
    except Exception as e:
        print(f"\n⚠️ CRITICAL ERROR during planning stage: {e}")
        print("   This might be because the planner's models are not found or configured.")
        print("   Falling back to using the original query as the only sub-query.")
        subqueries = [user_q]

    print("\n🧩 Split sub-queries:")
    for i, sq in enumerate(subqueries, 1):
        print(f"{i:02d}. {sq}")
    # --- END OF PLANNER INTEGRATION ---

    # Per-subquery retrieval
    per_subq_traces: List[SubqueryTrace] = []
    all_result_lists: List[List[Dict[str, Any]]] = []

    async def run_one(sq: str):
        print(f"\n🔍 DEBUG: Running retrieval for subquery: '{sq}'")
        result = await service.retrieve_subquery(
            query_text=sq,
            top_k=5,
            similarity_threshold=0.0,  # ← FIXED: Set to 0.0 to ensure results
            min_results=1,
            threshold_relax_factor=0.8,
            min_similarity_floor=0.05,
            project_id="proj_test_456"
        )
        print(f"🔍 DEBUG: Retrieval result - success: {result.success}, num_results: {len(result.results) if result.results else 0}")
        return result

    for sq in subqueries:
        rr = asyncio.run(run_one(sq))
        if not rr.success:
            print(f"\n❌ Retrieval failed for: {sq}")
            per_subq_traces.append(SubqueryTrace(subquery=sq, success=False, num_results=0, results=[]))
            all_result_lists.append([])
            continue

        print(f"\n✅ Retrieved {len(rr.results)} nodes for: {sq}")
        for j, n in enumerate(rr.results[:3], 1):
            meta = getattr(n.node, "metadata", {}) or {}
            print(f"   {j:02d}. score={n.score:.4f}  chunk_id={getattr(n.node, 'id_', 'na')}  title='{_source_title(meta)}'")

        results_as_dicts = [_serialize_node_with_score(x) for x in rr.results]
        per_subq_traces.append(SubqueryTrace(subquery=sq, success=True, num_results=len(rr.results), results=results_as_dicts))
        all_result_lists.append(results_as_dicts)

    # Fuse results
    print("\n🧪 Fusing results...")
    fuser = FusionEngine(k=60, token_budget=1500, skip_dedup=False)
    fused_chunks, fusion_stats = fuser.fuse_with_stats(all_result_lists, fetch_sources_by_ids)

    print(f"🔍 DEBUG: Fusion produced {len(fused_chunks)} final chunks")

    # Synthesize answer
    answer_text = synthesize_answer_from_chunks(fused_chunks)
    print("\n📜 Synthesized Answer:\n")
    print(answer_text)

    # Persist trace
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out_dir)
    ensure_dir(out_dir)

    trace = RunTrace(
        run_id=run_id,
        query=user_q,
        subqueries=subqueries,
        per_subquery=per_subq_traces,
        fusion={"stats": fusion_stats.to_dict(), "final_chunks": [_serialize_chunk(c) for c in fused_chunks]},
        answer={"type": "synthetic_summary", "text": answer_text}
    )

    out_path = out_dir / f"{timestamp}-{run_id}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(asdict(trace), f, ensure_ascii=False, indent=2)

    print(f"\n💾 Saved full trace to: {out_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())