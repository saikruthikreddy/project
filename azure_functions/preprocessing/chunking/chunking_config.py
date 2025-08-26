# chunking_config.py

CHUNKING_PARAMETERS = {
    "formal": {
        "max_tokens": 1000,
        "min_chunk_tokens": 100,
        "overlap_tokens": 100
    },
    "data_heavy": {
        "max_tokens_table": 1500,
        "max_tokens_prose": 1000,
        "min_chunk_tokens": 50
    },
    "presentation": {
        "slide_group_size": 3,
        "slide_stride": 1
    }
}
