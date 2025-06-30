import os
import json
import re
from statistics import mean
import google.generativeai as genai
from giani_pkb.utils.prompt_loader import load_prompt_template
from giani_pkb.core.project_service import get_project_purpose

# Configure Gemini API
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

def calculate_word_count(text):
    return len(text.strip().split()) if text and text.strip() else None

def calculate_average_title_word_length(titles):
    valid_titles = [t for t in titles if t and isinstance(t, str)]
    if not valid_titles:
        return 18  # fallback
    word_counts = [len(t.strip().split()) for t in valid_titles]
    return round(mean(word_counts))

def generate_titles(payload):
    try:
        # Extract inputs
        user_topic = payload.get("userIntentTopic", "").strip()
        user_instructions = payload.get("userIntentInstructions", "").strip()
        slide_title = payload.get("currentSlideTitle", "").strip()
        slide_statement = payload.get("currentSlideStatement", "").strip()
        slide_content = payload.get("currentSlideContent", "").strip()
        immediate_prev_statement = payload.get("immediatelyPreviousSlideStatement", "").strip()
        second_prev_statement = payload.get("secondPreviousSlideStatement", "").strip()
        previous_titles = payload.get("previousSlidesTitle", []) or []
        already_suggested = payload.get("alreadySuggestedTitles", []) or []
        new_instruction = payload.get("specificInstructionforNewset", "").strip()
        project_id = payload.get("projectID", "").strip()
        is_regeneration = payload.get("isRegeneration", False)

        # Calculate average word length range for the titles
        average_length = calculate_average_title_word_length(previous_titles)
        topical_threshold = 10
        lower_bound = max(5, int(average_length * 0.8))
        upper_bound = int(average_length * 1.2)
        word_range_str = f"{lower_bound} to {upper_bound} words"
        is_target_style_topical = average_length <= topical_threshold

        # Project purpose fallback
        project_purpose = (
            get_project_purpose(project_id).strip()
            if project_id else "General presentation objective"
        )

        # Previous titles fallback
        prev1 = previous_titles[0] if len(previous_titles) > 0 else ""
        prev2 = previous_titles[1] if len(previous_titles) > 1 else ""

        # 🔀 Choose correct prompt template based on isRegeneration flag
        prompt_filename = (
            "ppt_addin_prompts/title_regeneration_prompt.txt"
            if is_regeneration else
            "ppt_addin_prompts/title_generation_prompt.txt"
        )
        prompt_template = load_prompt_template(prompt_filename)

        # Format the prompt
        filled_prompt = prompt_template.format(
            currentProjectPurpose=project_purpose,
            userIntentTopic=user_topic or "Not specified",
            currentSlideTitle=slide_title or "Untitled",
            currentSlideStatement=slide_statement or "Untitled",
            currentSlideContent=slide_content or "No content provided.",
            immediatelyPreviousSlideTitle=prev1 or "No previous title",
            secondPreviousSlideTitle=prev2 or "No second previous title",
            immediatelyPreviousSlideStatement=immediate_prev_statement or "No previous statement",
            secondPreviousSlideStatement=second_prev_statement or "No second previous statement",
            userIntentInstructions=user_instructions or "No tone or focus given.",
            alreadySuggestedTitles="\n".join(already_suggested) if already_suggested else "None",
            specificInstructionforNewset=new_instruction or "None",
            targetStatementLengthRange=word_range_str,
            isTargetStyleTopical="True" if is_target_style_topical else "False"
        )

        # Generate titles using Gemini
        model = genai.GenerativeModel("gemini-1.5-pro")
        response = model.generate_content(filled_prompt)
        response_text = response.text.strip()

        # Extract suggestions
        suggestions = [
            re.sub(r"^\d+\.\s*", "", line.strip())
            for line in response_text.split("\n")
            if re.match(r"^\d+\.\s*", line.strip())
        ]
        if len(suggestions) < 3:
            suggestions = [
                line.strip("- ").strip()
                for line in response_text.split("\n")
                if line.strip()
            ]

        return {
            "success": True,
            "modelUsed": "gemini-1.5-pro",
            "suggestedTitles": suggestions[:3]
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "suggestedTitles": []
        }
