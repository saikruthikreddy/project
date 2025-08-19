# Updated strategies.py

import logging
import uuid
import csv
import re
import math
from io import StringIO
from typing import List, Dict, Any, Optional, Tuple
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_experimental.text_splitter import SemanticChunker
from langchain_openai import OpenAIEmbeddings

from azure_functions.preprocessing.chunking.models import ChunkMetadata
from azure_functions.preprocessing.chunking.token_counter import TokenCounter
from azure_functions.preprocessing.chunking.nlp_processor import NLPProcessor
from azure_functions.preprocessing.chunking.chunking_config import CHUNKING_PARAMETERS
from azure_functions.preprocessing.chunking.validators import validate_blocks_for_chunking

logger = logging.getLogger(__name__)

# Initialize globals
token_counter = TokenCounter()
nlp_processor = NLPProcessor()

def set_token_model(model_name: str):
    token_counter.set_model(model_name)

# Helper functions - deduplicated
def _center(b):
    return (b[0]+b[2]/2.0, b[1]+b[3]/2.0)

def _dist(b1, b2):
    return math.hypot(_center(b1)[0]-_center(b2)[0], _center(b1)[1]-_center(b2)[1])

def _normalized_bbox(meta):
    b = meta.get("bbox")
    if not b:
        return None
    units = meta.get("bbox_units")
    page_w = meta.get("page_width")
    page_h = meta.get("page_height")
    if units in ("pptx_emu", "px") and page_w and page_h:
        left, top, w, h = b
        return (left / page_w, top / page_h, w / page_w, h / page_h)
    elif units == "sheet_coordinates":
        return None
    return None

def _center_norm(b):
    return (b[0] + b[2]/2.0, b[1] + b[3]/2.0)

def _dist_norm(b1, b2):
    return math.hypot(_center_norm(b1)[0] - _center_norm(b2)[0],
                      _center_norm(b1)[1] - _center_norm(b2)[1])

def pair_metrics_with_labels(blocks, max_dist_norm=0.08):  # normalized threshold
    import re

    remaining, paired = [], []
    used = set()
    by_page = {}

    for idx, (text, meta) in enumerate(blocks):
        pg = meta.get("slide_number") or meta.get("page_number")
        by_page.setdefault(pg, []).append((idx, text, meta))

    for pg, items in by_page.items():
        metrics = [
            (i, t, m) for i, t, m in items if (
                m.get("element_type") == "metric" or
                m.get("block_type") == "metric" or
                (len((t or "").split()) <= 8 and re.search(r'(\d[\d,\.]*\s?%|\$\s?\d+|\d+\s?[xX])', t))
            )
        ]
        labels = [
            (i, t, m) for i, t, m in items if i not in [i for i, _, _ in metrics] and m.get("bbox")
        ]

        for i_m, t_m, m_m in metrics:
            if i_m in used or not m_m.get("bbox"):
                continue
            best = None
            for i_l, t_l, m_l in labels:
                if i_l in used or not m_l.get("bbox"):
                    continue
                b_m = _normalized_bbox(m_m)
                b_l = _normalized_bbox(m_l)
                if not b_m or not b_l:
                    continue
                d = _dist_norm(b_m, b_l)
                if d <= max_dist_norm and (best is None or d < best[0]):
                    best = (d, i_l, t_l, m_l)

            if best:
                _, i_l, t_l, m_l = best
                used.update([i_m, i_l])
                sentence = f"{t_m.strip()} {t_l.strip()}"

                pgnum = m_m.get("slide_number") or m_m.get("page_number")
                gid = str(uuid.uuid4())

                # Data chunk
                metric_meta = ChunkMetadata(
                    document_id=m_m.get("document_id", ""),
                    project_id=m_m.get("project_id", ""),
                    source_page_numbers=[pgnum] if pgnum else [],
                    chunk_type="metric",
                    structural_metadata={
                        "role": "data",
                        "bbox": m_m.get("bbox"),
                        "label_bbox": m_l.get("bbox"),
                        "caption": m_l.get("caption"),
                        "section": m_l.get("section_heading")
                    }
                )
                metric_meta.same_table_group_id = gid
                paired.append((sentence, metric_meta))

                # Context label chunk
                label_meta = ChunkMetadata(
                    document_id=metric_meta.document_id,
                    project_id=metric_meta.project_id,
                    source_page_numbers=metric_meta.source_page_numbers,
                    chunk_type="metric",
                    structural_metadata={
                        "role": "context",
                        "bbox": m_l.get("bbox"),
                        "caption": m_l.get("caption"),
                        "section": m_l.get("section_heading")
                    }
                )
                label_meta.same_table_group_id = gid
                paired.append((t_l.strip(), label_meta))

        for i, t, m in items:
            if i not in used:
                remaining.append((t, m))

    return paired, remaining


def _create_chunk_metadata(
    document_id: str,
    project_id: str,
    source_blocks_metadata: List[Dict[str, Any]],
    chunk_type_str: str,
    current_heading_info: Optional[Dict[str, Any]] = None
) -> ChunkMetadata:
    """Helper to create ChunkMetadata, aggregating page/slide numbers and structural info."""

    def extract_page_number(meta: Dict[str, Any]) -> Optional[int]:
        if not isinstance(meta, dict):
            return None
        return meta.get("page_number") or (meta.get("metadata", {}).get("page_number") if isinstance(meta.get("metadata"), dict) else None)

    def extract_slide_number(meta: Dict[str, Any]) -> Optional[int]:
        if not isinstance(meta, dict):
            return None
        return meta.get("slide_number") or (meta.get("metadata", {}).get("slide_number") if isinstance(meta.get("metadata"), dict) else None)

    try:
        page_numbers = sorted(list(set(
            extract_page_number(meta) for meta in source_blocks_metadata
            if meta and extract_page_number(meta) is not None
        )))
        slide_numbers = sorted(list(set(
            extract_slide_number(meta) for meta in source_blocks_metadata
            if meta and extract_slide_number(meta) is not None
        )))

        struct_meta = {
            "source_block_types": [],
        }

        if source_blocks_metadata and isinstance(source_blocks_metadata, list):
            valid_source_metas = [m for m in source_blocks_metadata if isinstance(m, dict)]
            struct_meta["source_block_types"] = [meta.get("block_type", "unknown") for meta in valid_source_metas]

            if valid_source_metas:
                first_meta = valid_source_metas[0]
                struct_meta["primary_block_type"] = first_meta.get("block_type", "unknown")
                nested_meta = first_meta.get("metadata", {}) if isinstance(first_meta.get("metadata"), dict) else {}
                combined_meta = {**nested_meta, **first_meta}

                # ⬇️ Add important structural fields
                for key in ["bbox", "style_name", "sheet_name", "row_numbers", "column_names",
                            "element_type", "region_type", "section", "caption", "subtype"]:
                    if key in combined_meta:
                        struct_meta[key] = combined_meta[key]

        # ⬇️ Heading info support
        if current_heading_info and isinstance(current_heading_info, dict):
            struct_meta["current_heading_text"] = current_heading_info.get("text")
            struct_meta["current_heading_level"] = current_heading_info.get("level")
            struct_meta["current_heading_source"] = current_heading_info.get("source")

        return ChunkMetadata(
            document_id=document_id,
            project_id=project_id,
            source_page_numbers=page_numbers,
            structural_metadata=struct_meta,
            chunk_type=chunk_type_str,
            slide_number=slide_numbers[0] if slide_numbers else None
        )

    except Exception as e:
        logger.error(f"Error creating chunk metadata for doc {document_id}, type {chunk_type_str}: {e}", exc_info=True)
        return ChunkMetadata(
            document_id=document_id,
            project_id=project_id,
            chunk_id=str(uuid.uuid4()),
            source_page_numbers=[],
            structural_metadata={"error": "metadata_creation_failed"},
            chunk_type=chunk_type_str if chunk_type_str else "unknown_error_chunk"
        )


def chunk_formal_document(
    parsed_blocks,
    document_id,
    project_id,
    max_tokens=CHUNKING_PARAMETERS["formal"]["max_tokens"],
    min_chunk_tokens=CHUNKING_PARAMETERS["formal"]["min_chunk_tokens"],
    overlap_tokens=CHUNKING_PARAMETERS["formal"]["overlap_tokens"],
    **kwargs  # Accept extra irrelevant parameters without crashing
):
    # Step 0: Peel off structured content first
    structured_chunks, prose_blocks = chunk_structured_elements(parsed_blocks, document_id, project_id)

    # Step 1: Run the formal prose logic on remaining blocks
    prose_chunks = _chunk_formal_prose_only(
        prose_blocks, document_id, project_id,
        max_tokens=max_tokens,
        min_chunk_tokens=min_chunk_tokens,
        overlap_tokens=overlap_tokens
    )

    # Step 2: Combine & re-index
    all_chunks = structured_chunks + prose_chunks
    for i, (_, meta) in enumerate(all_chunks):
        meta.chunk_index = i
        if i > 0:
            meta.previous_chunk_id = all_chunks[i - 1][1].chunk_id

    return all_chunks

def _chunk_formal_prose_only(
    prose_blocks,
    document_id,
    project_id,
    max_tokens,
    min_chunk_tokens,
    overlap_tokens
):
    chunks = []
    current_chunk_text = ""
    current_blocks_metadata = []
    current_heading_info = None
    carry = ""

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=max_tokens,
        chunk_overlap=overlap_tokens,
        length_function=token_counter.count_tokens,
        separators=["\n\n", "\n", ". ", " ", ""]
    )

    for block_text, block_metadata in prose_blocks:
        headings = nlp_processor.detect_headings_in_block(block_text, block_metadata)

        if headings:
            if current_chunk_text.strip():
                chunk_type_str = "prose"
                if (
                    current_heading_info and
                    len(current_chunk_text.strip().split()) < 12 and
                    not current_chunk_text.strip().endswith(('.', '!', '?'))
                ):
                    chunk_type_str = "heading"

                chunk_metadata = _create_chunk_metadata(
                    document_id, project_id, current_blocks_metadata, chunk_type_str, current_heading_info
                )
                if chunk_type_str == "heading":
                    chunk_metadata.structural_metadata["heading_level"] = current_heading_info.get("level", 1)
                if chunks:
                    chunk_metadata.previous_chunk_id = chunks[-1][1].chunk_id
                chunks.append((current_chunk_text.strip(), chunk_metadata))

            head_text, h_start, h_end, h_meta = headings[0]
            pre = block_text[:h_start].strip()
            head = block_text[h_start:h_end].strip()
            post = block_text[h_end:].strip()

            if pre:
                pre_meta = _create_chunk_metadata(document_id, project_id, [block_metadata], "prose", current_heading_info)
                if chunks:
                    pre_meta.previous_chunk_id = chunks[-1][1].chunk_id
                chunks.append((pre, pre_meta))

            head_meta = _create_chunk_metadata(
                document_id, project_id, [block_metadata], "heading",
                {"text": head_text, "level": h_meta.get("level", 1), "source": h_meta.get("source", "unknown")}
            )
            head_meta.structural_metadata["heading_level"] = h_meta.get("level", 1)
            if chunks:
                head_meta.previous_chunk_id = chunks[-1][1].chunk_id
            chunks.append((head, head_meta))

            current_heading_info = {
                "text": head_text,
                "level": h_meta.get("level", 1),
                "source": h_meta.get("source", "unknown")
            }
            current_chunk_text = post
            current_blocks_metadata = [block_metadata] if post else []
            continue

        else:
            current_chunk_text += "\n\n" + block_text if current_chunk_text else block_text
            current_blocks_metadata.append(block_metadata)

            if token_counter.count_tokens(current_chunk_text) > max_tokens:
                sub_chunks = text_splitter.split_text(current_chunk_text)
                for sub in sub_chunks:
                    sub = (carry + " " + sub).strip() if carry else sub
                    if token_counter.count_tokens(sub) < min_chunk_tokens:
                        carry = sub
                        continue
                    carry = ""

                    chunk_type_str = "prose"
                    if (
                        current_heading_info and
                        len(sub.strip().split()) < 12 and
                        not sub.strip().endswith(('.', '!', '?'))
                    ):
                        chunk_type_str = "heading"

                    chunk_metadata = _create_chunk_metadata(
                        document_id, project_id, current_blocks_metadata, chunk_type_str, current_heading_info
                    )
                    if chunk_type_str == "heading":
                        chunk_metadata.structural_metadata["heading_level"] = current_heading_info.get("level", 1)
                    if chunks:
                        chunk_metadata.previous_chunk_id = chunks[-1][1].chunk_id
                    chunks.append((sub.strip(), chunk_metadata))

                current_chunk_text = ""
                current_blocks_metadata = []
                current_heading_info = None

    # ✅ FINAL FLUSH
    if current_chunk_text.strip() or carry:
        final_text = (carry + " " + current_chunk_text).strip() if carry else current_chunk_text.strip()
        if final_text:
            is_table_block = any(
                isinstance(m, dict) and m.get("block_type", "").lower() == "table"
                for m in current_blocks_metadata
            )

            chunk_type_str = "prose"
            if (
                current_heading_info and
                len(final_text.strip().split()) < 12 and
                not final_text.strip().endswith(('.', '!', '?'))
            ):
                chunk_type_str = "heading"
            elif not current_heading_info and is_table_block:
                chunk_type_str = "table"

            chunk_metadata = _create_chunk_metadata(
                document_id, project_id, current_blocks_metadata, chunk_type_str, current_heading_info
            )

            if chunk_type_str == "heading":
                chunk_metadata.structural_metadata["heading_level"] = current_heading_info.get("level", 1)
            if chunks:
                chunk_metadata.previous_chunk_id = chunks[-1][1].chunk_id

            chunks.append((final_text.strip(), chunk_metadata))

    return chunks


def chunk_conversational_record(
    parsed_blocks: List[Tuple[str, Dict[str, Any]]],
    document_id: str,
    project_id: str,
    max_tokens: int = 300,
    overlap_tokens: int = 50
) -> List[Tuple[str, ChunkMetadata]]:
    """
    Chunk conversational records (transcripts, chat logs, etc.) by speaker turns.
    """
    chunks = []
    current_chunk_text = ""
    current_blocks_metadata = []
    current_speaker = None
    carry = ""  # 🔧 Fix: carry-over buffer for short chunks

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=max_tokens,
        chunk_overlap=overlap_tokens,
        length_function=token_counter.count_tokens,
        separators=["\n", ". ", " ", ""]
    )

    for block_text, block_metadata in parsed_blocks:
        speakers = nlp_processor.detect_speakers(block_text)

        if speakers:
            if current_chunk_text.strip():
                chunk_metadata = _create_chunk_metadata(
                    document_id, project_id, current_blocks_metadata, "dialogue_turn"
                )
                chunk_metadata.speaker_attribution = current_speaker
                if chunks:
                    chunk_metadata.previous_chunk_id = chunks[-1][1].chunk_id
                chunks.append((current_chunk_text.strip(), chunk_metadata))

            current_chunk_text = block_text
            current_blocks_metadata = [block_metadata]
            current_speaker = speakers[0][0] if speakers else None

        else:
            current_chunk_text += "\n" + block_text if current_chunk_text else block_text
            current_blocks_metadata.append(block_metadata)

            if token_counter.count_tokens(current_chunk_text) > max_tokens:
                sub_chunks = text_splitter.split_text(current_chunk_text)
                for sub in sub_chunks:
                    sub = (carry + " " + sub).strip() if carry else sub
                    if token_counter.count_tokens(sub) < 50:
                        carry = sub
                        continue
                    carry = ""
                    chunk_metadata = _create_chunk_metadata(
                        document_id, project_id, current_blocks_metadata, "dialogue_turn"
                    )
                    chunk_metadata.speaker_attribution = current_speaker
                    if chunks:
                        chunk_metadata.previous_chunk_id = chunks[-1][1].chunk_id
                    chunks.append((sub.strip(), chunk_metadata))

                current_chunk_text = ""
                current_blocks_metadata = []
                current_speaker = None

    # Handle remaining content
    final_text = (carry + " " + current_chunk_text).strip() if carry else current_chunk_text.strip()
    if final_text:
        chunk_metadata = _create_chunk_metadata(
            document_id, project_id, current_blocks_metadata, "dialogue_turn"
        )
        chunk_metadata.speaker_attribution = current_speaker
        if chunks:
            chunk_metadata.previous_chunk_id = chunks[-1][1].chunk_id
        chunks.append((final_text, chunk_metadata))

    return chunks


# NEW FUNCTION: structure-aware chunking
def chunk_structured_elements(
    parsed_blocks: List[Tuple[str, Dict[str, Any]]],
    document_id: str,
    project_id: str
) -> Tuple[List[Tuple[str, ChunkMetadata]], List[Tuple[str, Dict[str, Any]]]]:
    """
    Extracts atomic chunks for tables and charts, and adds their contextual captions.
    Leaves prose blocks for further downstream chunking.
    """
    structured_chunks: List[Tuple[str, ChunkMetadata]] = []
    prose_blocks: List[Tuple[str, Dict[str, Any]]] = []

    # Grouping by slide_number or page_number for safety
    current_group_id_by_slide = {}

    for text, meta in parsed_blocks:
        block_type = meta.get("block_type", "prose")
        page_number = meta.get("page_number")
        slide_number = meta.get("slide_number")
        bbox = meta.get("bbox")
        caption = meta.get("caption") or meta.get("structural_metadata", {}).get("table_caption") \
                                        or meta.get("structural_metadata", {}).get("chart_caption")
        section = meta.get("structural_metadata", {}).get("heading_context")
        region_type = meta.get("structural_metadata", {}).get("region_type")

        if block_type in ["table", "chart"]:
            element_type = "table" if block_type == "table" else "chart"
            chunk_type = element_type

            # 🔐 Determine grouping scope
            scope_key = slide_number if slide_number is not None else page_number
            if scope_key is not None:
                group_id = current_group_id_by_slide.get(scope_key)
                if not group_id:
                    group_id = str(uuid.uuid4())
                    current_group_id_by_slide[scope_key] = group_id
            else:
                group_id = str(uuid.uuid4())

            # 🔍 Subtype classification (fragment, rows_only, full)
            subtype = meta.get("table_subtype")
            if not subtype and block_type == "table":
                rows = text.strip().split("\n")
                if len(rows) <= 2:
                    subtype = "fragment"
                elif not meta.get("column_names"):
                    subtype = "rows_only"
                else:
                    subtype = "full"

            # 📦 Compose structural_metadata
            structural_metadata = {
                "bbox": bbox,
                "caption": caption,
                "section": section,
                "element_type": element_type,
                "region_type": region_type
            }
            if subtype:
                structural_metadata["subtype"] = subtype
            if "column_names" in meta:
                structural_metadata["column_names"] = meta["column_names"]

            # 📌 Atomic chunk
            meta_atomic = ChunkMetadata(
                document_id=document_id,
                project_id=project_id,
                source_page_numbers=[page_number] if page_number is not None else [],
                chunk_type=chunk_type,
                structural_metadata=structural_metadata
            )
            meta_atomic.same_table_group_id = group_id
            meta_atomic.chunk_index = len(structured_chunks)
            meta_atomic.slide_number = slide_number  # <-- (from Fix #1)
            structured_chunks.append((text, meta_atomic))

            # 💬 Context chunk
            if caption or section:
                context_text = "\n\n".join(filter(None, [caption, section]))
                meta_context = ChunkMetadata(
                    document_id=document_id,
                    project_id=project_id,
                    source_page_numbers=[page_number] if page_number is not None else [],
                    chunk_type=f"{chunk_type}_context",
                    structural_metadata={
                        "bbox": bbox,
                        "caption": caption,
                        "section": section,
                        "element_type": f"{element_type}_context",
                        "region_type": region_type
                    }
                )
                meta_context.same_table_group_id = group_id
                meta_context.chunk_index = len(structured_chunks)
                meta_context.slide_number = slide_number  # <-- (from Fix #1)
                structured_chunks.append((context_text, meta_context))

        else:
            prose_blocks.append((text, meta))

    return structured_chunks, prose_blocks


def chunk_data_heavy_document(
    parsed_blocks, document_id, project_id,
    max_tokens_table=CHUNKING_PARAMETERS["data_heavy"]["max_tokens_table"],
    max_tokens_prose=CHUNKING_PARAMETERS["data_heavy"]["max_tokens_prose"],
    min_chunk_tokens=CHUNKING_PARAMETERS["data_heavy"]["min_chunk_tokens"]
):
    if not parsed_blocks:
        return []

    final_chunks_with_meta: List[Tuple[str, ChunkMetadata]] = []

    validate_blocks_for_chunking(parsed_blocks)

    try:
        # ✅ STEP 1: Use structure-aware chunking first
        structured_chunks, remaining_blocks = chunk_structured_elements(parsed_blocks, document_id, project_id)
        final_chunks_with_meta.extend(structured_chunks)

        # ✅ STEP 2: Re-process remaining blocks with original logic
        prose_blocks_buffer: List[Tuple[str, Dict[str, Any]]] = []

        for i_block_dh, block_tuple_dh in enumerate(remaining_blocks):
            try:
                if not isinstance(block_tuple_dh, tuple) or len(block_tuple_dh) != 2:
                    logger.warning(f"DocID {document_id}: Skipping malformed block in data_heavy at index {i_block_dh}.")
                    continue

                block_text, block_meta = block_tuple_dh
                if not isinstance(block_text, str) or not isinstance(block_meta, dict):
                    logger.warning(f"DocID {document_id}: Skipping block with invalid types in data_heavy at index {i_block_dh}.")
                    continue

                if not block_text.strip():
                    continue

                block_type_fp = block_meta.get("block_type", "unknown")
                source_type_fp = block_meta.get("source_type", "text")
                is_table_or_data = source_type_fp in ["table", "tabular_data"] or block_type_fp in ["table", "row_group_data"]
                is_image = source_type_fp == "image" or block_type_fp == "image_text"

                # ✅ Fix 2 — Explicitly treat sheet_summary as prose but tag it
                if block_type_fp == "sheet_summary":
                    prose_blocks_buffer.append((block_text, {**block_meta, "summary_block": True}))
                    continue

                if is_table_or_data or is_image:
                    # Flush prose chunks collected so far
                    if prose_blocks_buffer:
                        prose_chunks = chunk_formal_document(
                            prose_blocks_buffer, document_id, project_id,
                            max_tokens=max_tokens_prose, min_chunk_tokens=min_chunk_tokens
                        )
                        final_chunks_with_meta.extend(prose_chunks)
                        prose_blocks_buffer = []

                    if is_table_or_data:
                        current_max_tokens = max_tokens_table
                        if token_counter.count_tokens(block_text) > current_max_tokens:
                            text_splitter_table = RecursiveCharacterTextSplitter(
                                chunk_size=current_max_tokens,
                                chunk_overlap=50,
                                length_function=token_counter.count_tokens
                            )
                            header, rows = split_table_header_rows(block_text)
                            splits = text_splitter_table.split_text("\n".join(rows))

                            for split in splits:
                                if not split.strip():
                                    continue
                                part = header + "\n" + split
                                meta = _create_chunk_metadata(document_id, project_id, [block_meta], "table")
                                meta.same_table_group_id = block_meta.get("table_id") or str(uuid.uuid4())
                                meta.structural_metadata["subtype"] = "fragment"
                                final_chunks_with_meta.append((part, meta))
                        else:
                            meta = _create_chunk_metadata(document_id, project_id, [block_meta], "table")
                            meta.structural_metadata["subtype"] = "rows_only" if block_type_fp != "table" else "full"
                            final_chunks_with_meta.append((block_text, meta))

                    elif is_image:
                        meta = _create_chunk_metadata(document_id, project_id, [block_meta], "image_text")
                        meta.structural_metadata["subtype"] = "image_text"
                        final_chunks_with_meta.append((block_text, meta))

                else:
                    prose_blocks_buffer.append((block_text, block_meta))

            except Exception as e_block_data_heavy:
                logger.error(f"DocID {document_id}: Error processing a block in chunk_data_heavy_document: {e_block_data_heavy}", exc_info=True)
                continue

        # ✅ Final prose flush
        if prose_blocks_buffer:
            prose_chunks = chunk_formal_document(
                prose_blocks_buffer, document_id, project_id,
                max_tokens=max_tokens_prose, min_chunk_tokens=min_chunk_tokens
            )
            final_chunks_with_meta.extend(prose_chunks)

        # ✅ Set chunk_index and link previous_chunk_id
        for i, (_, meta) in enumerate(final_chunks_with_meta):
            meta.chunk_index = i
            if i > 0:
                meta.previous_chunk_id = final_chunks_with_meta[i - 1][1].chunk_id

        return final_chunks_with_meta

    except Exception as e_main_data_heavy:
        logger.error(f"DocID {document_id}: Failed to process in chunk_data_heavy_document: {e_main_data_heavy}", exc_info=True)
        return []


def chunk_document_semantic(
    parsed_blocks: List[Tuple[str, Dict[str, Any]]],
    document_id: str,
    project_id: str,
    embeddings_model_instance: Any,
    breakpoint_threshold_type: str = "percentile",  # Can be: "percentile", "standard_deviation", etc.
    **kwargs
) -> List[Tuple[str, ChunkMetadata]]:
    """
    Chunk documents using semantic similarity across full document text,
    preserving page numbers and source metadata per chunk.
    """
    chunks: List[Tuple[str, ChunkMetadata]] = []

    try:
        # Build unified text and track offsets for each block
        full_text_parts = []
        block_offsets = []
        block_metas = []
        cursor = 0

        for text, meta in parsed_blocks:
            if not text.strip():
                continue
            full_text_parts.append(text)
            start = cursor
            cursor += len(text) + 2  # +2 for "\n\n" spacing
            end = cursor
            block_offsets.append((start, end))
            block_metas.append(meta)

        full_text = "\n\n".join(full_text_parts)

        # Create semantic chunker and perform split
        semantic_chunker = SemanticChunker(
            embeddings=embeddings_model_instance,
            breakpoint_threshold_type=breakpoint_threshold_type,
            **kwargs
        )

        semantic_chunks = semantic_chunker.split_text(full_text)

        def find_overlapping_metas(start_char: int, end_char: int) -> List[Dict[str, Any]]:
            """Find metadata from blocks overlapping with this chunk span."""
            overlapping = []
            for (block_start, block_end), meta in zip(block_offsets, block_metas):
                if not (end_char <= block_start or start_char >= block_end):  # i.e., overlap exists
                    overlapping.append(meta)
            return overlapping

        def extract_pages(metas: List[Dict[str, Any]]) -> List[int]:
            pages = set()
            for meta in metas:
                pg = meta.get("page_number") or meta.get("metadata", {}).get("page_number")
                if pg is not None:
                    pages.add(pg)
            return sorted(pages)

        running_offset = 0
        for i, chunk_text in enumerate(semantic_chunks):
            chunk_text = chunk_text.strip()
            if not chunk_text:
                continue

            start_char = full_text.find(chunk_text, running_offset)
            if start_char == -1:
                continue  # Should not happen, but skip if not found
            end_char = start_char + len(chunk_text)
            running_offset = end_char

            overlapping_metas = find_overlapping_metas(start_char, end_char)

            chunk_metadata = _create_chunk_metadata(
                document_id=document_id,
                project_id=project_id,
                source_blocks_metadata=overlapping_metas,
                chunk_type_str="semantic"
            )

            chunk_metadata.source_page_numbers = extract_pages(overlapping_metas)
            chunk_metadata.chunk_index = len(chunks)
            if chunks:
                chunk_metadata.previous_chunk_id = chunks[-1][1].chunk_id

            chunks.append((chunk_text, chunk_metadata))

        return chunks

    except Exception as e:
        logger.error(f"Error in semantic chunking for doc {document_id}: {e}", exc_info=True)
        return []


def chunk_presentation_document(
    parsed_blocks, document_id, project_id,
    slide_group_size=CHUNKING_PARAMETERS["presentation"]["slide_group_size"],
    slide_stride=CHUNKING_PARAMETERS["presentation"]["slide_stride"],
    **kwargs
):
    """
    Chunk presentation documents by grouping slides with structure-aware processing.
    """
    chunks = []
    slides = {}

    # Group blocks by slide number
    for block_text, block_metadata in parsed_blocks:
        slide_number = block_metadata.get("slide_number") or block_metadata.get("page_number")
        if slide_number is not None:
            if slide_number not in slides:
                slides[slide_number] = []
            slides[slide_number].append((block_text, block_metadata))

    sorted_slide_numbers = sorted(slides.keys())

    for i in range(0, len(sorted_slide_numbers), slide_stride):
        slide_group_numbers = sorted_slide_numbers[i:i + slide_group_size]
        if not slide_group_numbers:
            continue

        structured_chunks = []
        prose_blocks = []

        # Step 1: Collect all blocks from the current group of slides
        slide_blocks = []
        for slide_number in slide_group_numbers:
            slide_blocks.extend(slides.get(slide_number, []))

        # Step 2: Apply structure-aware chunking
        per_slide_structured_chunks, per_slide_prose = chunk_structured_elements(
            slide_blocks, document_id, project_id
        )

        # 🔧 Add slide_range metadata to structured chunks
        for _, meta in per_slide_structured_chunks:
            meta.structural_metadata["slide_range"] = [slide_group_numbers[0], slide_group_numbers[-1]]
            meta.slide_number = slide_group_numbers[0]  # Optional: for better filtering

        structured_chunks.extend(per_slide_structured_chunks)
        prose_blocks.extend(per_slide_prose)

        chunks.extend(structured_chunks)

        # Step 3: Merge prose chunks for this slide group
        from langchain.text_splitter import RecursiveCharacterTextSplitter

        if prose_blocks:
            chunk_text = "\n\n".join([text for text, _ in prose_blocks])
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=400,
                chunk_overlap=60,
                length_function=token_counter.count_tokens
            )
            subchunks = splitter.split_text(chunk_text)

            for sub in subchunks:
                if not sub.strip():
                    continue
                meta = _create_chunk_metadata(document_id, project_id, [m for _, m in prose_blocks], "slide_group")
                meta.slide_number = slide_group_numbers[0]
                meta.structural_metadata["slide_range"] = [slide_group_numbers[0], slide_group_numbers[-1]]
                if chunks:
                    meta.previous_chunk_id = chunks[-1][1].chunk_id
                chunks.append((sub.strip(), meta))

    # ✅ Reindex and link
    for i, (_, meta) in enumerate(chunks):
        meta.chunk_index = i
        if i > 0:
            meta.previous_chunk_id = chunks[i - 1][1].chunk_id

    return chunks


def split_table_header_rows(table_text: str) -> Tuple[str, List[str]]:
    lines = [line.strip() for line in table_text.strip().split('\n') if line.strip()]

    if not lines:
        return "", []

    # Case 1: Markdown-style with pipe and separator (| and ---)
    if "|" in lines[0]:
        if len(lines) > 1 and re.match(r'^\s*\|?\s*[-:| ]+\s*\|?', lines[1]):
            header = lines[0]
            rows = lines[2:]
            return header, rows

        # Fallback: check for consistent pipe count
        col_count = lines[0].count("|")
        multi_line_header = [lines[0]]
        for i in range(1, len(lines)):
            if lines[i].count("|") == col_count:
                multi_line_header.append(lines[i])
            else:
                break
        header = "\n".join(multi_line_header)
        rows = lines[len(multi_line_header):]
        return header, rows

    # Case 2: CSV-style (comma-separated)
    if "," in lines[0]:
        reader = csv.reader(StringIO("\n".join(lines)))
        all_rows = list(reader)
        if len(all_rows) > 1 and len(all_rows[0]) == len(all_rows[1]):
            header = ",".join(all_rows[0])
            rows = [",".join(row) for row in all_rows[1:]]
            return header, rows

    # Fallback: treat first line as header
    header = lines[0]
    rows = lines[1:]
    return header, rows

# In strategies.py

def chunk_document_adaptive(
    parsed_blocks: List[Tuple[str, Dict[str, Any]]],
    document_id: str,
    project_id: str,
    document_type: str = "formal",
    use_semantic_chunker: bool = False,
    openai_api_key: Optional[str] = None,
    token_model: Optional[str] = None,
    embeddings=None,  # ✅ Accepts external embedding instance
    **kwargs
) -> List[Tuple[str, ChunkMetadata]]:
    if token_model:
        set_token_model(token_model)

    DOCUMENT_TYPE_TO_STRATEGY_MAP = {
        "conversational": chunk_conversational_record,
        "data_heavy": chunk_data_heavy_document,
        "presentation": chunk_presentation_document,
        "pptx_file": chunk_presentation_document,
        "slide_deck": chunk_presentation_document,
        "formal": chunk_formal_document,
    }

    chunks = []  # Initialize chunks list

    # ✅ NEW WIRING LOGIC STARTS HERE
    # This block intercepts relevant document types to run the metric pairing first.
    if document_type in {"data_heavy", "presentation", "pptx_file", "slide_deck", "formal"}:
        # Step 1: Peel off metric chunks
        metric_chunks, rest_blocks = pair_metrics_with_labels(parsed_blocks)
        chunks.extend(metric_chunks) # Add paired metrics to our final list

        # The blocks that remain are passed to the next stage
        blocks_for_next_stage = rest_blocks
    else:
        # For other types, all blocks go to the next stage
        blocks_for_next_stage = parsed_blocks
    # ✅ NEW WIRING LOGIC ENDS HERE

    if use_semantic_chunker:
        try:
            embeddings_model = embeddings or OpenAIEmbeddings(openai_api_key=openai_api_key)
            # Run semantic chunking on the remaining (non-metric) blocks
            semantic_chunks_result = chunk_document_semantic(
                parsed_blocks=blocks_for_next_stage,
                document_id=document_id,
                project_id=project_id,
                embeddings_model_instance=embeddings_model,
                **kwargs
            )
            chunks.extend(semantic_chunks_result)
        except Exception as e:
            logger.warning(f"Semantic chunking failed, falling back to type-based chunking: {e}")
            strategy = DOCUMENT_TYPE_TO_STRATEGY_MAP.get(document_type, chunk_formal_document)
            # Run the strategy on the remaining (non-metric) blocks
            strategy_chunks = strategy(blocks_for_next_stage, document_id, project_id, **kwargs)
            chunks.extend(strategy_chunks)
    else:
        strategy = DOCUMENT_TYPE_TO_STRATEGY_MAP.get(document_type, chunk_formal_document)
        # Run the strategy on the remaining (non-metric) blocks
        strategy_chunks = strategy(blocks_for_next_stage, document_id, project_id, **kwargs)
        chunks.extend(strategy_chunks)

    # ✅ Set global chunk ordering for ALL chunks (metrics + others)
    for i, (_, meta) in enumerate(chunks):
        meta.chunk_index = i
        if i > 0:
            meta.previous_chunk_id = chunks[i - 1][1].chunk_id

    return chunks