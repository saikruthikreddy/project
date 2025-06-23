import os
import google.generativeai as genai
from giani_pkb.utils.prompt_loader import load_prompt_template
from giani_pkb.core.project_service import get_project_purpose

# Configure Gemini API
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

def refine_title(payload):
    """
    Refine a specific slide title using Gemini based on user refinement instructions,
    slide content, previous slides, and overall project purpose.
    """

    try:
        # Extract and sanitize payload fields
        user_topic = payload.get("userIntentTopic", "").strip()
        user_instructions = payload.get("userIntentInstructions", "").strip()  # NOT used directly in prompt
        current_slide_title = payload.get("currentSlideTitle", "").strip()
        current_slide_content = payload.get("currentSlideContent", "").strip()
        previous_titles = payload.get("previousSlidesTitle", []) or []

        title_to_refine = payload.get("titleToBeRefined", "").strip()
        user_refinement_instruction = payload.get("userRefinementInstructions", "").strip()
        already_suggested_refinements = payload.get("alreadySuggestedRefinements", []) or []
        project_id = payload.get("projectID", "").strip()

        if not title_to_refine:
            return {
                "success": False,
                "error": "titleToBeRefined is required",
                "refinedSuggestions": [],
                "contextUsed": {}
            }

        # Get project purpose
        project_purpose = (
            get_project_purpose(project_id).strip()
            if project_id else "General project objective"
        )

        # Load and fill the prompt
        prompt_template = load_prompt_template("ppt_addin_prompts/title_refine_prompt.txt")

        filled_prompt = prompt_template.format(
            currentProjectPurpose=project_purpose,
            titleToRefine=title_to_refine,
            currentSlideContent=current_slide_content or "No content.",
            previousSlidesTitle="\n".join(previous_titles) if previous_titles else "None",
            userRefinementInstructions=user_refinement_instruction or "Improve tone and clarity.",
            alreadySuggestedRefinements="\n".join(already_suggested_refinements) if already_suggested_refinements else "None"
        )

        # Call Gemini to generate refined titles
        response = model.generate_content(filled_prompt)
        suggestions = [s.strip() for s in response.text.strip().split("\n") if s.strip()]

        return {
            "success": True,
            "refinedSuggestions": suggestions[:3],
            "contextUsed": {
                "refinedFrom": title_to_refine,
                "userRefinementInstructions": user_refinement_instruction,
                "projectPurposeUsed": project_purpose,
                "slideContentLength": len(current_slide_content),
                "previousTitlesCount": len(previous_titles),
                "alreadySuggestedCount": len(already_suggested_refinements)
            }
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Error refining title: {str(e)}",
            "refinedSuggestions": [],
            "contextUsed": {
                "refinedFrom": payload.get("titleToBeRefined", "Unknown"),
                "projectPurposeUsed": payload.get("projectPurpose", "N/A")
            }
        }
