import os
import json
import google.generativeai as genai
from giani_pkb.utils.prompt_loader import load_prompt_template
from giani_pkb.services.project_service import get_project_purpose

# Configure Gemini API
from giani_pkb.utils.config import GEMINI_API_KEY, GEMINI_PRO_MODEL, GEMINI_FLASH_MODEL
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(GEMINI_FLASH_MODEL)

def review_slide(payload):
    """
    Review a slide using Giani’s consulting communication principles.
    Returns:
        - reviewReport: structured JSON feedback from Gemini
        - contextUsed: metadata for traceability
    Raises:
        - ValueError for invalid input or bad LLM response
        - RuntimeError for unexpected system issues
    """
    # Extract and sanitize payload fields
    current_statement = payload.get("currentSlideStatement", "").strip()
    current_content = payload.get("currentSlideContent", "").strip()
    prev_statement_1 = payload.get("immediatelyPreviousSlideStatement", "").strip()
    prev_statement_2 = payload.get("secondPreviousSlideStatement", "").strip()
    project_id = payload.get("projectID", "").strip()

    if not current_statement or not current_content or not project_id:
        raise ValueError("currentSlideStatement, currentSlideContent, and projectID are required.")

    # Always fetch project purpose from project ID
    project_purpose = get_project_purpose(project_id).strip()

    # Load the prompt template
    prompt_template = load_prompt_template("ppt_addin_prompts/slide_review_prompt.txt")

    # Fill the prompt
    filled_prompt = prompt_template.format(
        currentSlideStatement=current_statement or "N/A",
        currentSlideContent=current_content or "N/A",
        immediatelyPreviousSlideStatement=prev_statement_1 or "N/A",
        secondPreviousSlideStatement=prev_statement_2 or "N/A",
        currentProjectPurpose=project_purpose or "General objective"
    )

    try:
        # Call Gemini LLM
        response = model.generate_content(filled_prompt)

        # Parse LLM response into JSON
        review_json = json.loads(response.text.strip())

        # Validate structure
        if not isinstance(review_json, dict) or "detailedFeedback" not in review_json:
            raise ValueError("Model response is malformed or missing 'detailedFeedback'.")

        # Return result — no wrapping, just data
        return {
            "reviewReport": review_json,
            "contextUsed": {
                "projectID": project_id,
                "projectPurposeUsed": project_purpose,
                "slideStatement": current_statement,
                "slideContentLength": len(current_content),
                "immediatelyPreviousSlideStatementIncluded": bool(prev_statement_1),
                "secondPreviousSlideStatementIncluded": bool(prev_statement_2)
            }
        }

    except json.JSONDecodeError as je:
        raise ValueError(f"Model response is not valid JSON: {je}")
    except Exception as e:
        raise RuntimeError(f"Error during Gemini review: {str(e)}")
