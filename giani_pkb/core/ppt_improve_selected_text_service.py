import os
import google.generativeai as genai
from giani_pkb.utils.prompt_loader import load_prompt_template
from giani_pkb.core.project_service import get_project_purpose

# Configure Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

def refine_selected_text(payload):
    """
    Refine a user-selected text using Gemini and consulting-style principles.
    Returns a single improved version.
    """
    try:
        # Extract fields safely
        selected_text = payload.get("selectedTextContent", "").strip()
        user_instructions = payload.get("userRefinementInstructions", "").strip()
        slide_statement = payload.get("currentSlideStatement", "").strip()
        previous_snippet = payload.get("immediatelyPreviousTextSnippet", "").strip()
        already_suggested = payload.get("alreadySuggestedRefinements", []) or []
        project_id = payload.get("projectID", "").strip()
        project_purpose = payload.get("currentProjectPurpose", "").strip()

        # Get project purpose if not directly passed
        if not project_purpose and project_id:
            project_purpose = get_project_purpose(project_id).strip()

        # Load the LLM prompt template
        prompt_template = load_prompt_template("ppt_addin_prompts/improveSelectedText_prompt.txt")

        # Fill the prompt
        filled_prompt = prompt_template.format(
            selectedTextContent=selected_text or "N/A",
            userRefinementInstructions=user_instructions or "No specific instructions.",
            currentSlideStatement=slide_statement or "N/A",
            immediatelyPreviousTextSnippet=previous_snippet or "N/A",
            currentProjectPurpose=project_purpose or "General objective",
            alreadySuggestedRefinements="\n".join(already_suggested)
        )

        print(f"--- PROMPT (ProjectID: {project_id}) ---\n{filled_prompt}")

        # Call Gemini model
        response = model.generate_content(filled_prompt)
        suggestions = [
            line.strip()
            for line in response.text.strip().split("\n")
            if line.strip() and line.strip() not in already_suggested
        ]

        # Return only the first refined version
        top_suggestion = suggestions[0] if suggestions else ""

        return {
            "success": True,
            "refinedText": top_suggestion,
            "contextUsed": {
                "selectedTextContent": selected_text,
                "userRefinementInstructions": user_instructions,
                "projectID": project_id,
                "projectPurposeUsed": project_purpose,
                "alreadySuggestedCount": len(already_suggested),
                "slideStatementIncluded": bool(slide_statement),
                "previousSnippetIncluded": bool(previous_snippet)
            }
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Error refining text: {str(e)}",
            "refinedText": "",
            "contextUsed": {}
        }