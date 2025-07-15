"""
Utility for generating summarization prompts based on document groups.
"""
from giani_pkb.utils.prompt_loader import load_prompt_template
from giani_pkb.utils.constants import DocumentGroup, CATEGORY_TO_GROUP_MAPPING

def get_group_a_prompt(originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
    """Generate prompt for Group A documents (strategy, financial, formal deliverables)."""
    prompt_template = load_prompt_template("summarization_group_a_prompt.txt")
    return prompt_template.format(
        originalFilename=originalFilename,
        documentSourceType=documentSourceType,
        userNoteOnPurpose=userNoteOnPurpose,
        key_document_chunks_for_processing=key_document_chunks
    )

def get_group_b_prompt(originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
    """Generate prompt for Group B documents (research, analysis, data)."""
    prompt_template = load_prompt_template("summarization_group_b_prompt.txt")
    return prompt_template.format(
        originalFilename=originalFilename,
        documentSourceType=documentSourceType,
        userNoteOnPurpose=userNoteOnPurpose,
        key_document_chunks_for_processing=key_document_chunks
    )

def get_group_c_prompt(originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
    """Generate prompt for Group C documents (working drafts, internal documents)."""
    prompt_template = load_prompt_template("summarization_group_c_prompt.txt")
    return prompt_template.format(
        originalFilename=originalFilename,
        documentSourceType=documentSourceType,
        userNoteOnPurpose=userNoteOnPurpose,
        key_document_chunks_for_processing=key_document_chunks
    )

def get_group_d_prompt(originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
    """Generate prompt for Group D documents (working drafts, internal documents)."""
    prompt_template = load_prompt_template("summarization_group_d_prompt.txt")
    return prompt_template.format(
        originalFilename=originalFilename,
        documentSourceType=documentSourceType,
        userNoteOnPurpose=userNoteOnPurpose,
        key_document_chunks_for_processing=key_document_chunks
    )

def get_appropriate_prompt(document_category: str, originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
    
    group = CATEGORY_TO_GROUP_MAPPING.get(document_category, DocumentGroup.GROUP_D)
    try:
        if group == DocumentGroup.GROUP_A:
            return get_group_a_prompt(originalFilename, documentSourceType, userNoteOnPurpose, key_document_chunks)
        elif group == DocumentGroup.GROUP_B:
            return get_group_b_prompt(originalFilename, documentSourceType, userNoteOnPurpose, key_document_chunks)
        elif group == DocumentGroup.GROUP_C:
            return get_group_c_prompt(originalFilename, documentSourceType, userNoteOnPurpose, key_document_chunks)
        else:  # GROUP_D
            return get_group_d_prompt(originalFilename, documentSourceType, userNoteOnPurpose, key_document_chunks)
    except Exception as e:
        raise
