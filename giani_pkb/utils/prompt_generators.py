"""
Utility for generating summarization prompts based on document groups.
"""
from giani_pkb.utils.prompt_loader import load_prompt_template

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

def get_appropriate_prompt(document_category: str, originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
    """Get the appropriate prompt based on document category."""
    from giani_pkb.utils.constants import DocumentGroup, CATEGORY_TO_GROUP_MAPPING

    print(f"[GET_PROMPT] Document category: {repr(document_category)}", flush=True)
    
    group = CATEGORY_TO_GROUP_MAPPING.get(document_category, DocumentGroup.GROUP_D)
    print(f"[GET_PROMPT] Mapped to group: {group}", flush=True)

    try:
        if group == DocumentGroup.GROUP_A:
            print(f"[GET_PROMPT] Using Group A prompt", flush=True)
            return get_group_a_prompt(originalFilename, documentSourceType, userNoteOnPurpose, key_document_chunks)
        elif group == DocumentGroup.GROUP_B:
            print(f"[GET_PROMPT] Using Group B prompt", flush=True)
            return get_group_b_prompt(originalFilename, documentSourceType, userNoteOnPurpose, key_document_chunks)
        elif group == DocumentGroup.GROUP_C:
            print(f"[GET_PROMPT] Using Group C prompt", flush=True)
            return get_group_c_prompt(originalFilename, documentSourceType, userNoteOnPurpose, key_document_chunks)
        else:  # GROUP_D
            print(f"[GET_PROMPT] Using Group D prompt", flush=True)
            return get_group_d_prompt(originalFilename, documentSourceType, userNoteOnPurpose, key_document_chunks)
    except Exception as e:
        print(f"[GET_PROMPT ERROR] Error in prompt generation: {e}", flush=True)
        raise

def get_group_d_prompt(originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
    """Generate prompt for Group D documents (meetings, communications, generic)."""
    print(f"[GROUP_D] Loading template for Group D", flush=True)
    try:
        prompt_template = load_prompt_template("summarization_group_d_prompt.txt")
        print(f"[GROUP_D] Template loaded successfully, length: {len(prompt_template)}", flush=True)
        print(f"[GROUP_D] Template preview (first 500 chars): {repr(prompt_template[:500])}", flush=True)
        
        # Let's also check what placeholders are in the template
        import re
        placeholders = re.findall(r'\{([^}]+)\}', prompt_template)
        print(f"[GROUP_D] Found placeholders: {placeholders}", flush=True)
        
        # Check for malformed placeholders
        for placeholder in placeholders:
            if '\n' in placeholder or '  ' in placeholder:
                print(f"[GROUP_D] ⚠ MALFORMED PLACEHOLDER FOUND: {repr(placeholder)}", flush=True)
        
        result = prompt_template.format(
            originalFilename=originalFilename,
            documentSourceType=documentSourceType,
            userNoteOnPurpose=userNoteOnPurpose,
            key_document_chunks_for_processing=key_document_chunks
        )
        print(f"[GROUP_D] Template formatted successfully", flush=True)
        return result
        
    except Exception as e:
        print(f"[GROUP_D ERROR] Error in Group D prompt: {e}", flush=True)
        print(f"[GROUP_D ERROR] Error type: {type(e).__name__}", flush=True)
        raise
