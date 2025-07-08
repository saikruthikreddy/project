import os
import google.generativeai as genai
from giani_pkb.utils.prompt_loader import load_prompt_template
from giani_pkb.services.project_service import get_project_purpose

# Configure Gemini API
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

def refine_title(payload):
    """
    Refine a specific title or key statement using Gemini based on user instructions.
    Returns refined suggestions and context used (without wrapping success or error).
    """

    # Extract and sanitize payload fields
    statement_to_refine = payload.get("statementToRefine", "").strip()
    user_instruction = payload.get("userRefinementInstructions", "").strip()
    current_slide_content = payload.get("currentSlideContent", "").strip()
    immediately_prev_statement = payload.get("immediatelyPreviousSlideStatement", "").strip()
    already_suggested = payload.get("alreadySuggestedRefinements", []) or []
    project_id = payload.get("projectID", "").strip()

    if not statement_to_refine:
        raise ValueError("statementToRefine is required")

    # Get project purpose (used in context)
    project_purpose = (
        get_project_purpose(project_id).strip()
        if project_id else "General project objective"
    )

    # Load and fill the prompt template
    prompt_template = load_prompt_template("ppt_addin_prompts/title_refine_prompt.txt")
    filled_prompt = prompt_template.format(
        statementToRefine=statement_to_refine,
        userRefinementInstructions=user_instruction or "Improve tone and clarity.",
        currentSlideContent=current_slide_content or "No content.",
        immediatelyPreviousSlideStatement=immediately_prev_statement or "None",
        alreadySuggestedRefinements="\n".join(already_suggested) if already_suggested else "None"
    )

    print(f"--- REFINE TITLE PROMPT ---\n{filled_prompt}")

    try:
        # Call Gemini LLM
        response = model.generate_content(filled_prompt)
        suggestions = [
            line.strip()
            for line in response.text.strip().split("\n")
            if line.strip()
        ]

        return {
            "refinedSuggestions": suggestions[:3],
            "contextUsed": {
                "refinedFrom": statement_to_refine,
                "userRefinementInstructions": user_instruction,
                "projectPurposeUsed": project_purpose,
                "slideContentLength": len(current_slide_content),
                "alreadySuggestedCount": len(already_suggested),
                "immediatelyPreviousSlideStatementIncluded": bool(immediately_prev_statement)
            }
        }

    except Exception as e:
        raise RuntimeError(f"Error refining title: {str(e)}")
