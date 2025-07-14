import os
import json
import google.generativeai as genai
from giani_pkb.utils.prompt_loader import load_prompt_template

# Configure Gemini
from giani_pkb.utils.config import GEMINI_API_KEY, GEMINI_PRO_MODEL, GEMINI_FLASH_MODEL
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(GEMINI_FLASH_MODEL)

def parallelize_statements(payload):
    """
    Rewrite a list of target statements to match the grammatical and stylistic structure of a reference statement.
    Returns a list of rewritten statements with parallel structure and context used.
    """
    # Extract and sanitize inputs
    reference_statement = payload.get("referenceStatement", "").strip()
    target_statements = payload.get("targetStatements", [])
    slide_statement = payload.get("currentSlideStatement", "").strip()
    project_id = payload.get("projectID", "").strip()

    # Ensure required inputs are present
    if not reference_statement or not target_statements:
        raise ValueError("Reference statement and target statements are required.")

    # Load the LLM prompt template
    prompt_template = load_prompt_template("ppt_addin_prompts/Parallelize_content_prompt.txt")

    # Format target statements list
    formatted_targets = "\n".join(f"- {s.strip()}" for s in target_statements if s.strip())

    # Fill in the prompt
    filled_prompt = prompt_template.format(
        referenceStatement=reference_statement,
        targetStatements=formatted_targets,
        currentSlideStatement=slide_statement or "N/A"
    )

    print(f"--- PARALLELIZE PROMPT (ProjectID: {project_id}) ---\n{filled_prompt}")

    # Call Gemini
    response = model.generate_content(filled_prompt)

    print("--- GEMINI RESPONSE TEXT ---")
    print(response.text)

    # Parse model response as JSON list
    try:
        suggestions = json.loads(response.text.strip())
    except json.JSONDecodeError as je:
        raise ValueError(f"Model response is not valid JSON: {je}")

    # Validate output format
    if not isinstance(suggestions, list) or len(suggestions) != len(target_statements):
        raise ValueError("Model response is invalid or misaligned with input count.")

    return {
        "parallelizedStatements": suggestions,
        "contextUsed": {
            "referenceStatement": reference_statement,
            "numTargets": len(target_statements),
            "projectID": project_id,
            "slideStatementIncluded": bool(slide_statement)
        }
    }
