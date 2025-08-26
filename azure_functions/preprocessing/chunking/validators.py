# validators.py

def validate_blocks_for_chunking(blocks: list[dict]) -> None:
    for i, block in enumerate(blocks):
        if not isinstance(block, tuple) or len(block) != 2:
            raise ValueError(f"Block {i}: Expected a (text, metadata) tuple.")
        
        text, meta = block
        if not isinstance(meta, dict):
            raise ValueError(f"Block {i}: Metadata should be a dictionary.")
        
        if "block_type" not in meta:
            raise ValueError(f"Block {i}: Missing 'block_type' in metadata.")

        if "page_number" not in meta and "slide_number" not in meta:
            raise ValueError(f"Block {i}: Missing 'page_number' or 'slide_number'.")

        if meta.get("block_type") == "table":
            if not meta.get("column_names"):
                raise ValueError(f"Block {i}: Table block missing 'column_names'.")
