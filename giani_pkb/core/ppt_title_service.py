import os
import google.generativeai as genai
from giani_pkb.utils.prompt_loader import load_prompt_template
from giani_pkb.core.project_service import get_project_purpose

# Configure Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

def generate_titles(payload):
    """
    Generate slide titles based on user intent, content, and project context
    using structured Gemini prompt logic.
    """
    try:
        # Safely extract all fields
        user_topic = payload.get("userIntentTopic", "").strip()
        user_instructions = payload.get("userIntentInstructions", "").strip()
        slide_title = payload.get("currentSlideTitle", "").strip()
        slide_content = payload.get("currentSlideContent", "").strip()
        previous_titles = payload.get("previousSlidesTitle", []) or []
        already_suggested = payload.get("alreadySuggestedTitles", []) or []
        new_instruction = payload.get("specificInstructionforNewset", "").strip()
        project_id = payload.get("projectID", "").strip()

        # Get project purpose
        project_purpose = (
            get_project_purpose(project_id).strip()
            if project_id else "General presentation objective"
        )

        # Load the refined, structured prompt template
        prompt_template = load_prompt_template("ppt_addin_prompts/title_generation_prompt.txt")

        # Fill the placeholders in the prompt
        filled_prompt = prompt_template.format(
            currentProjectPurpose=project_purpose,
            userIntentTopic=user_topic or "Not specified",
            currentSlideTitle=slide_title or "Untitled",
            currentSlideContent=slide_content or "No content provided.",
            previousSlidesTitle="\n".join(previous_titles) if previous_titles else "None",
            userIntentInstructions=user_instructions or "No tone or focus given.",
            alreadySuggestedTitles="\n".join(already_suggested) if already_suggested else "None",
            specificInstructionforNewset=new_instruction or "None"
        )

        # Call Gemini model
        response = model.generate_content(filled_prompt)
        suggestions = [
            line.strip()
            for line in response.text.strip().split("\n")
            if line.strip()
        ]

        return {
            "success": True,
            "suggestedTitles": suggestions[:3],
            "contextUsed": {
                "userIntentTopic": user_topic,
                "userIntentInstructions": user_instructions,
                "specificInstructionforNewset": new_instruction,
                "projectID": project_id,
                "projectPurposeUsed": project_purpose,
                "slideContentLength": len(slide_content),
                "previousTitlesCount": len(previous_titles),
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
