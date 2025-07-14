import os
import logging
import google.generativeai as genai
from giani_pkb.utils.prompt_loader import load_prompt_template
from giani_pkb.services.project_service import get_project_purpose

# Configure Gemini
from giani_pkb.utils.config import GEMINI_API_KEY, GEMINI_PRO_MODEL, GEMINI_FLASH_MODEL
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(GEMINI_FLASH_MODEL)

logger = logging.getLogger(__name__)

def generate_slide_structure(payload):
    """
    Generate slide structure with bullets, visuals, and layout suggestions based on user context.
    Supports regeneration flow to avoid repeat suggestions.
    """
    try:
        # Extract and clean payload inputs
        project_id = payload.get("projectID", "").strip()
        topic = payload.get("userIntentSlideTopic", "").strip()
        instructions = payload.get("userSpecificInstructions", "").strip()
        current_title = payload.get("currentSlideTitle", "").strip()
        current_content = payload.get("currentSlideContent", "").strip()
        previous_titles = payload.get("previousSlidesTitle", []) or []
        flow = payload.get("userIntentFlow", []) or []
        content_style = payload.get("userIntentContentStyle", []) or []

        # Regeneration-specific fields
        is_regenerate = payload.get("isRegenerate", False)
        already_suggested_raw = payload.get("alreadyGenerateSlideStructure", []) or []
        new_instruction = payload.get("instructionForNewStructure", "").strip()

        # Format past suggestions
        already_suggested_formatted = "\n".join(
            f"- {s}" for s in already_suggested_raw
        ) if already_suggested_raw else "None"

        # Get project purpose
        project_purpose = (
            get_project_purpose(project_id).strip()
            if project_id else "General presentation objective"
        )

        # Choose prompt template based on regenerate flag
        prompt_template_name = (
            "ppt_addin_prompts/Slide_structure_regenerate_prompt.txt"
            if is_regenerate else
            "ppt_addin_prompts/slide_structure_prompt.txt"
        )
        prompt_template = load_prompt_template(prompt_template_name)

        # Fill the prompt template
        filled_prompt = prompt_template.format(
            currentProjectPurpose=project_purpose,
            userIntentSlideTopic=topic or "Not specified",
            currentSlideTitle=current_title or "Untitled",
            currentSlideContent=current_content or "No content provided.",
            previousSlidesTitle="\n".join(previous_titles) if previous_titles else "None",
            userSpecificInstructions=instructions or "None",
            userIntentFlow="\n".join(flow) if flow else "None",
            alreadyGenerateSlideStructure=already_suggested_formatted,
            userIntentContentStyle="\n".join(content_style) if content_style else "None",
            instructionForNewStructure=new_instruction or "None"
        )

        logger.info("Slide structure prompt:\n%s", filled_prompt)

        # Call Gemini model
        response = model.generate_content(filled_prompt)

        # Prepare result — no success/error flags
        return {
            "structuredSlideOutput": response.text.strip(),
            "contextUsed": {
                "userIntentSlideTopic": topic,
                "userSpecificInstructions": instructions,
                "userIntentFlow": flow,
                "userIntentContentStyle": content_style,
                "projectID": project_id,
                "projectPurposeUsed": project_purpose,
                "previousTitlesCount": len(previous_titles),
                "slideContentLength": len(current_content),
                "instructionForNewStructure": new_instruction,
                "alreadySuggestedCount": len(already_suggested_raw)
            }
        }

    except Exception as e:
        logger.error("Slide structure generation failed: %s", str(e))
        # Let the route layer handle this properly using api_internal_server_error
        raise RuntimeError(f"Slide structure generation failed: {str(e)}")
