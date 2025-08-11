"""
Utility for generating summarization and metadata prompts based on document groups.
"""
from giani_pkb.utils.prompt_loader import load_prompt_template
from giani_pkb.utils.constants import DocumentGroup, CATEGORY_TO_GROUP_MAPPING


def get_group_a_summarization_prompt(originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
    """Generate summarization prompt for Group A documents (strategy, financial, formal deliverables)."""
    prompt_template = load_prompt_template("summarization_group_a_prompt.txt")
    return prompt_template.format(
        originalFilename=originalFilename,
        documentSourceType=documentSourceType,
        userNoteOnPurpose=userNoteOnPurpose,
        key_document_chunks_for_processing=key_document_chunks
    )


def get_group_a_metadata_prompt(originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
    """Generate metadata extraction prompt for Group A documents (strategy, financial, formal deliverables)."""
    prompt_template = load_prompt_template("metadata_group_a_prompt.txt")
    return prompt_template.format(
        originalFilename=originalFilename,
        documentSourceType=documentSourceType,
        userNoteOnPurpose=userNoteOnPurpose,
        key_document_chunks_for_processing=key_document_chunks
    )


def get_group_b_summarization_prompt(originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
    """Generate summarization prompt for Group B documents (research, analysis, data)."""
    prompt_template = load_prompt_template("summarization_group_b_prompt.txt")
    return prompt_template.format(
        originalFilename=originalFilename,
        documentSourceType=documentSourceType,
        userNoteOnPurpose=userNoteOnPurpose,
        key_document_chunks_for_processing=key_document_chunks
    )


def get_group_b_metadata_prompt(originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
    """Generate metadata extraction prompt for Group B documents (research, analysis, data)."""
    prompt_template = load_prompt_template("metadata_group_b_prompt.txt")
    return prompt_template.format(
        originalFilename=originalFilename,
        documentSourceType=documentSourceType,
        userNoteOnPurpose=userNoteOnPurpose,
        key_document_chunks_for_processing=key_document_chunks
    )


def get_group_c_summarization_prompt(originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
    """Generate summarization prompt for Group C documents (working drafts, internal documents)."""
    prompt_template = load_prompt_template("summarization_group_c_prompt.txt")
    return prompt_template.format(
        originalFilename=originalFilename,
        documentSourceType=documentSourceType,
        userNoteOnPurpose=userNoteOnPurpose,
        key_document_chunks_for_processing=key_document_chunks
    )


def get_group_c_metadata_prompt(originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
    """Generate metadata extraction prompt for Group C documents (working drafts, internal documents)."""
    prompt_template = load_prompt_template("metadata_group_c_prompt.txt")
    return prompt_template.format(
        originalFilename=originalFilename,
        documentSourceType=documentSourceType,
        userNoteOnPurpose=userNoteOnPurpose,
        key_document_chunks_for_processing=key_document_chunks
    )


def get_group_d_summarization_prompt(originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
    """Generate summarization prompt for Group D documents (working drafts, internal documents)."""
    prompt_template = load_prompt_template("summarization_group_d_prompt.txt")
    return prompt_template.format(
        originalFilename=originalFilename,
        documentSourceType=documentSourceType,
        userNoteOnPurpose=userNoteOnPurpose,
        key_document_chunks_for_processing=key_document_chunks
    )


def get_group_d_metadata_prompt(originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
    """Generate metadata extraction prompt for Group D documents (working drafts, internal documents)."""
    prompt_template = load_prompt_template("metadata_group_d_prompt.txt")
    return prompt_template.format(
        originalFilename=originalFilename,
        documentSourceType=documentSourceType,
        userNoteOnPurpose=userNoteOnPurpose,
        key_document_chunks_for_processing=key_document_chunks
    )


# Mapping for prompt functions
SUMMARIZATION_PROMPT_FUNCTIONS = {
    DocumentGroup.GROUP_A: get_group_a_summarization_prompt,
    DocumentGroup.GROUP_B: get_group_b_summarization_prompt,
    DocumentGroup.GROUP_C: get_group_c_summarization_prompt,
    DocumentGroup.GROUP_D: get_group_d_summarization_prompt,
}

METADATA_PROMPT_FUNCTIONS = {
    DocumentGroup.GROUP_A: get_group_a_metadata_prompt,
    DocumentGroup.GROUP_B: get_group_b_metadata_prompt,
    DocumentGroup.GROUP_C: get_group_c_metadata_prompt,
    DocumentGroup.GROUP_D: get_group_d_metadata_prompt,
}


def get_appropriate_prompt(document_category: str, originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
    """Get summarization prompt for backward compatibility."""
    group = CATEGORY_TO_GROUP_MAPPING.get(document_category, DocumentGroup.GROUP_D)
    try:
        prompt_function = SUMMARIZATION_PROMPT_FUNCTIONS[group]
        return prompt_function(originalFilename, documentSourceType, userNoteOnPurpose, key_document_chunks)
    except Exception as e:
        raise


def get_summarization_prompt(document_category: str, originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
    """Get summarization prompt based on document category."""
    group = CATEGORY_TO_GROUP_MAPPING.get(document_category, DocumentGroup.GROUP_D)
    try:
        prompt_function = SUMMARIZATION_PROMPT_FUNCTIONS[group]
        return prompt_function(originalFilename, documentSourceType, userNoteOnPurpose, key_document_chunks)
    except Exception as e:
        raise


def get_metadata_prompt(document_category: str, originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
    """Get metadata extraction prompt based on document category."""
    group = CATEGORY_TO_GROUP_MAPPING.get(document_category, DocumentGroup.GROUP_D)
    try:
        prompt_function = METADATA_PROMPT_FUNCTIONS[group]
        return prompt_function(originalFilename, documentSourceType, userNoteOnPurpose, key_document_chunks)
    except Exception as e:
        raise


def get_both_prompts(document_category: str, originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> tuple[str, str]:
    """Get both summarization and metadata prompts based on document category."""
    group = CATEGORY_TO_GROUP_MAPPING.get(document_category, DocumentGroup.GROUP_D)
    try:
        summarization_function = SUMMARIZATION_PROMPT_FUNCTIONS[group]
        metadata_function = METADATA_PROMPT_FUNCTIONS[group]
        
        summarization_prompt = summarization_function(originalFilename, documentSourceType, userNoteOnPurpose, key_document_chunks)
        metadata_prompt = metadata_function(originalFilename, documentSourceType, userNoteOnPurpose, key_document_chunks)
        
        return summarization_prompt, metadata_prompt
    except Exception as e:
        raise
