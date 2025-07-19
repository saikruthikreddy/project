import os
import re
import logging
from typing import Optional, Tuple
import google.generativeai as genai

from giani_pkb.utils.prompt_loader import load_prompt_template
from giani_pkb.services.project_service import get_project_purpose
from giani_pkb.utils.config import GEMINI_API_KEY, GEMINI_PRO_MODEL

# Setup logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

# Configure Gemini API
if GEMINI_API_KEY:
    logger.debug("✅ GEMINI_API_KEY found and configuring genai client.")
    genai.configure(api_key=GEMINI_API_KEY)
else:
    logger.error("❌ GEMINI_API_KEY not found. Please check environment setup.")

def calculate_word_count(text: Optional[str]) -> Optional[int]:
    if text and text.strip():
        return len(text.strip().split())
    return None

def prepare_length_and_style_inputs_with_variance_handling(
    immediatelyPreviousSlideStatement: Optional[str],
    secondPreviousSlideStatement: Optional[str],
    currentSlideStatement: Optional[str] = None
) -> Tuple[str, bool]:
    SHORT_WORD_COUNT_UPPER_BOUND = 8
    VARIANCE_ABS_DIFF_THRESHOLD = 5
    VARIANCE_RATIO_THRESHOLD = 2.5
    DEFAULT_LONG_RANGE_STR = "15-25 words"

    len1 = calculate_word_count(immediatelyPreviousSlideStatement)
    len2 = calculate_word_count(secondPreviousSlideStatement)

    if len1 is not None and len2 is not None:
        abs_diff = abs(len1 - len2)
        max_len, min_len = max(len1, len2), min(len1, len2)
        ratio_diff = float('inf') if min_len == 0 else max_len / min_len

        is_variance_high = (
            abs_diff > VARIANCE_ABS_DIFF_THRESHOLD or 
            ratio_diff > VARIANCE_RATIO_THRESHOLD
        )

        if is_variance_high:
            if max_len <= SHORT_WORD_COUNT_UPPER_BOUND:
                return f"{max(1, max_len - 2)}-{max_len + 2} words", True
            else:
                return f"{max(1, max_len - 3)}-{max_len + 3} words", False
        else:
            avg_len = (len1 + len2) / 2
            if avg_len <= SHORT_WORD_COUNT_UPPER_BOUND:
                return f"{max(1, int(avg_len) - 2)}-{int(avg_len) + 2} words", True
            else:
                return f"{max(1, int(avg_len) - 3)}-{int(avg_len) + 3} words", False

    single_prev_len = len1 if len1 is not None else len2
    if single_prev_len is not None:
        if single_prev_len <= SHORT_WORD_COUNT_UPPER_BOUND:
            return f"{max(1, single_prev_len - 2)}-{single_prev_len + 2} words", True
        else:
            return f"{max(1, single_prev_len - 3)}-{single_prev_len + 3} words", False

    current_len = calculate_word_count(currentSlideStatement)
    if current_len is not None:
        if current_len <= SHORT_WORD_COUNT_UPPER_BOUND:
            return f"{max(1, current_len - 2)}-{current_len + 2} words", True
        else:
            return f"{max(1, current_len - 3)}-{current_len + 3} words", False

    return DEFAULT_LONG_RANGE_STR, False

def generate_titles(payload):
    """
    Generates 2–3 title suggestions using Gemini based on current context.
    Returns: { suggestedTitles: [...], modelUsed: "...", contextUsed: {...} }
    """
    try:
        logger.debug("📥 [generate_titles] Payload received:")
        logger.debug(payload)

        user_topic = payload.get("userIntentTopic", "").strip()
        user_instructions = payload.get("userIntentInstructions", "").strip()
        slide_statement = payload.get("currentSlideStatement", "").strip()
        slide_content = payload.get("currentSlideContent", "").strip()
        immediate_prev_statement = payload.get("immediatelyPreviousSlideStatement", "").strip()
        second_prev_statement = payload.get("secondPreviousSlideStatement", "").strip()
        previous_titles = payload.get("previousSlidesTitle", []) or []
        already_suggested = payload.get("alreadySuggestedTitles", []) or []
        new_instruction = payload.get("specificInstructionforNewset", "").strip()
        project_id = payload.get("projectID", "").strip()
        is_regeneration = payload.get("isRegeneration", False)

        logger.debug("✅ Extracted variables:")
        logger.debug(f"userIntentTopic: {user_topic}")
        logger.debug(f"userIntentInstructions: {user_instructions}")
        logger.debug(f"currentSlideStatement: {slide_statement}")
        logger.debug(f"currentSlideContent: {slide_content}")
        logger.debug(f"immediatelyPreviousSlideStatement: {immediate_prev_statement}")
        logger.debug(f"secondPreviousSlideStatement: {second_prev_statement}")
        logger.debug(f"previousSlidesTitle: {previous_titles}")
        logger.debug(f"alreadySuggestedTitles: {already_suggested}")
        logger.debug(f"specificInstructionforNewset: {new_instruction}")
        logger.debug(f"projectID: {project_id}")
        logger.debug(f"isRegeneration: {is_regeneration}")

        word_range_str, is_target_style_topical = prepare_length_and_style_inputs_with_variance_handling(
            immediate_prev_statement,
            second_prev_statement,
            slide_statement
        )

        logger.debug(f"📏 Determined word range: {word_range_str}, Topical Style: {is_target_style_topical}")

        project_purpose = (
            get_project_purpose(project_id).strip()
            if project_id else "General presentation objective"
        )
        logger.debug(f"🎯 Project purpose fetched: {project_purpose}")

        prev1 = previous_titles[0] if len(previous_titles) > 0 else ""
        prev2 = previous_titles[1] if len(previous_titles) > 1 else ""

        prompt_filename = (
            "ppt_addin_prompts/title_regeneration_prompt.txt"
            if is_regeneration else
            "ppt_addin_prompts/title_generation_prompt.txt"
        )
        logger.debug(f"📄 Loading prompt template from: {prompt_filename}")
        prompt_template = load_prompt_template(prompt_filename)

        filled_prompt = prompt_template.format(
            currentProjectPurpose=project_purpose,
            userIntentTopic=user_topic or "Not specified",
            currentSlideStatement=slide_statement or "Untitled",
            currentSlideContent=slide_content or "No content provided.",
            immediatelyPreviousSlideTitle=prev1 or "No previous title",
            secondPreviousSlideTitle=prev2 or "No second previous title",
            immediatelyPreviousSlideStatement=immediate_prev_statement or "No previous statement",
            secondPreviousSlideStatement=second_prev_statement or "No second previous statement",
            userIntentInstructions=user_instructions or "No tone or focus given.",
            alreadySuggestedStatements="\n".join(already_suggested) if already_suggested else "None",
            specificInstructionforNewset=new_instruction or "None",
            targetStatementLengthRange=word_range_str,
            isTargetStyleTopical="True" if is_target_style_topical else "False"
        )

        logger.debug("🧩 [Gemini Prompt] Filled prompt:\n" + filled_prompt)

        model = genai.GenerativeModel(GEMINI_PRO_MODEL)
        logger.debug("🧠 Gemini model initialized with: " + GEMINI_PRO_MODEL)

        response = model.generate_content(filled_prompt)
        response_text = response.text.strip()

        logger.debug("[🎯 Gemini Response] Raw output:\n" + response_text)

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
        
        logger.debug("✅ Parsed suggestions:")
        logger.debug(suggestions)

        return {
            "suggestedTitles": suggestions[:3],
            "modelUsed": GEMINI_PRO_MODEL,
            "contextUsed": {
                "userIntentTopic": user_topic,
                "projectID": project_id,
                "projectPurposeUsed": project_purpose,
                "wordRangeSuggested": word_range_str,
                "isTargetStyleTopical": is_target_style_topical,
                "previousTitleCount": len(previous_titles),
                "alreadySuggestedCount": len(already_suggested)
            }
        }

    except Exception as e:
        logger.exception("❌ Failed to generate slide titles due to error:")
        raise RuntimeError(f"Failed to generate slide titles: {str(e)}")
