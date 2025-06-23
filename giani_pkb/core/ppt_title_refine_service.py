#  core/ppt_title_refine_service.py (Title Refinement Service)
# ================================
import os
import google.generativeai as genai
from giani_pkb.utils.prompt_loader import load_prompt_template

# Configure Gemini API
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

def refine_title(payload):
    """
    Refine a specific slide title based on user context and feedback
    """
    try:
        # Extract payload data with defaults
        topic = payload.get("userIntentTopic", "")
        instructions = payload.get("userIntentInstructions", "")
        current_title = payload.get("currentSlideTitle", "")
        content = payload.get("currentSlideContent", "")
        prev_titles = payload.get("previousSlidesTitle", [])
        title_to_refine = payload.get("titleToBeRefined", "")
        currentProjectPurpose = payload.get("projectPurpose", "General presentation")

        # Validate essential fields
        if not title_to_refine:
            return {
                "success": False,
                "error": "titleToBeRefined is required",
                "refinedSuggestions": [],
                "contextUsed": {}
            }

        # Load prompt template
        prompt_template = load_prompt_template("ppt_addin_prompts/title_refine_prompt.txt")

        # Fill prompt template
        filled_prompt = prompt_template.format(
        userIntentTopic=topic,
        userIntentInstructions=instructions,
        specificInstructionforNewset=specific_instruction,
        currentSlideTitle=current_title,
        currentSlideContent=content,
        previousSlidesTitle="\n".join(prev_titles) if prev_titles else "None",
        currentProjectPurpose=project_purpose  # ✅ this fixes the KeyError
    )


        # Generate refined suggestions using Gemini
        response = model.generate_content(filled_prompt)
        
        # Parse suggestions
        suggestions = [s.strip() for s in response.text.strip().split("\n") if s.strip()]

        return {
            "success": True,
            "refinedSuggestions": suggestions[:3],  # Return top 3 refined options
            "contextUsed": {
                "refinedFrom": title_to_refine,
                "projectPurposeUsed": project_purpose,
                "userIntentTopic": topic,
                "slideContentConsidered": bool(content),
                "previousTitlesCount": len(prev_titles)
            }
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": f"Error refining title: {str(e)}",
            "refinedSuggestions": [],
            "contextUsed": {
                "refinedFrom": title_to_refine,
                "projectPurposeUsed": project_purpose
            }
        }
