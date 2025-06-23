# core/ppt_title_service.py (Title Generation Service)
# ================================
import os
import google.generativeai as genai
from giani_pkb.utils.prompt_loader import load_prompt_template
from giani_pkb.core.project_service import get_project_purpose

# Configure Gemini API
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

def generate_titles(payload):
    """
    Generate slide titles based on user intent and context
    """
    try:
        # Extract payload data with defaults
        topic = payload.get('userIntentTopic', '')
        instructions = payload.get('userIntentInstructions', '')
        current_title = payload.get('currentSlideTitle', '')
        content = payload.get('currentSlideContent', '')
        prev_titles = payload.get('previousSlidesTitle', [])
        already_suggested = payload.get('alreadySuggestedTitles', [])
        specific_instruction = payload.get('specificInstructionforNewset', '')
        project_id = payload.get('projectID', '')

        # Fetch project purpose from CSV DB
        project_purpose = get_project_purpose(project_id) if project_id else "General presentation"

        # Load prompt template
        prompt_template = load_prompt_template("ppt_addin_prompts/title_generation_prompt.txt")


        # Fill prompt template
        filled_prompt = prompt_template.format(
        userIntentTopic=topic,
        userIntentInstructions=instructions,
        specificInstructionforNewset=specific_instruction,
        currentSlideTitle=current_title,
        currentSlideContent=content,
        previousSlidesTitle="\n".join(prev_titles) if prev_titles else "None",
        alreadySuggested="\n".join(already_suggested) if already_suggested else "None",
        currentProjectPurpose=project_purpose  # ✅ this fixes the KeyError
    )


        # Generate content using Gemini
        response = model.generate_content(filled_prompt)
        
        # Parse suggestions (assuming they come separated by newlines)
        suggestions = [s.strip() for s in response.text.strip().split("\n") if s.strip()]
        
        return {
            "success": True,
            "suggestedTitles": suggestions[:3],  # Return top 3
            "contextUsed": {
                "userIntentTopic": topic,
                "slideContentConsidered": bool(content),
                "specificInstructionforNewset": specific_instruction,
                "projectID": project_id,
                "projectPurposeUsed": project_purpose,
                "previousTitlesCount": len(prev_titles),
                "alreadySuggestedCount": len(already_suggested)
            }
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": f"Error generating titles: {str(e)}",
            "suggestedTitles": [],
            "contextUsed": {}
        }
