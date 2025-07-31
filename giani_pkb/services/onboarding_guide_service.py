"""
Service for generating the Project Onboarding Guide.
"""

import logging
import json
from typing import Dict, Any, List, Optional

from giani_pkb.database.database_manager import DatabaseManager
from giani_pkb.utils.config import GEMINI_API_KEY
from giani_pkb.utils.gemini_client import initialize_gemini_client
import google.generativeai as genai


class OnboardingGuideGenerator:
    """
    Orchestrates the generation of the Project Onboarding Guide.
    """

    def __init__(self, db_manager: DatabaseManager, gemini_api_key: Optional[str] = None):
        self.logger = logging.getLogger(__name__)
        self.db_manager = db_manager
        self.gemini_api_key = gemini_api_key or GEMINI_API_KEY
        if not self.gemini_api_key:
            raise ValueError("Gemini API key must be provided.")
        initialize_gemini_client(self.gemini_api_key)
        self.model = genai.GenerativeModel('gemini-pro')

    def generate_onboarding_guide(self, project_id: int) -> Dict[str, Any]:
        """
        Generates the project onboarding guide for a given project_id.
        """
        self.logger.info(f"Generating onboarding guide for project_id: {project_id}")

        # Step 1: Data Aggregation
        project_context = self._get_project_context(project_id)
        document_summaries = self._get_document_summaries(project_id)

        # Step 2: AI-Powered Synthesis
        mission_and_approach = self._synthesize_mission_and_approach(project_context, document_summaries)
        strategic_intelligence_readout = self._synthesize_strategic_intelligence_readout(document_summaries)
        priority_reading_list = self._identify_priority_reading_list(document_summaries)
        knowledge_base_faq = self._generate_knowledge_base_faq(document_summaries)

        # Step 3: Data Aggregation & Caching
        onboarding_guide = {
            "projectName": project_context.get("name"),
            "lastSynthesized": "2025-06-18T10:00:00Z",  # TODO: Use current time
            "missionAndApproach": mission_and_approach,
            "knowledgeAtAGlance": {
                "documentsProcessed": len(document_summaries),
                "keyThemesIdentified": len(set(theme for s in document_summaries for theme in s.get("key_themes", []))),
                "mustReadDocuments": len(priority_reading_list.get("highPriority", [])),
                "distributionBySource": self._get_distribution_by_source(document_summaries),
            },
            "strategicIntelligenceReadout": self._format_strategic_intelligence_readout(strategic_intelligence_readout),
            "priorityReadingList": priority_reading_list.get("priorityReadingList"),
            "knowledgeFAQ": knowledge_base_faq.get("knowledgeFAQ", []),
        }

        # TODO: Implement caching

        return onboarding_guide

    def _get_project_context(self, project_id: int) -> Dict[str, Any]:
        """
        Retrieves project context from the database.
        """
        self.logger.info(f"Getting project context for project_id: {project_id}")
        project = self.db_manager.get_project(project_id)
        if project:
            return project.to_dict_detailed()
        return {}

    def _get_document_summaries(self, project_id: int) -> List[Dict[str, Any]]:
        """
        Retrieves document summaries from the database.
        """
        self.logger.info(f"Getting document summaries for project_id: {project_id}")
        documents = self.db_manager.get_project_documents(project_id)
        summaries = []
        for doc in documents:
            summary = self.db_manager.get_document_summary(doc.id)
            if summary:
                summaries.append(summary)
        return summaries

    def _synthesize_mission_and_approach(self, project_context: Dict[str, Any], document_summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Synthesizes the 'Mission & Approach' section of the onboarding guide.
        """
        self.logger.info("Synthesizing 'Mission & Approach' section")

        sow_and_proposal_summaries = [
            s for s in document_summaries
            if s.get("document_category") in ["SoW / Proposal Document", "Project Plan"]
        ]

        if not sow_and_proposal_summaries:
            return {
                "projectMandate": "N/A",
                "keyProjectPhases": [],
                "coreAnalyticalWorkstreams": [],
            }

        prompt = f"""
        You are a Giani.ai AI Strategist, acting as an experienced Engagement Manager. Your task is to distill foundational project documents into a clear and concise "Mission & Approach" briefing for a new consultant joining the team. The output must be professional, strategically sound, and easy to understand at a glance.

        CONTEXT PROVIDED:
        You will be given two key pieces of information:

        1.  **`projectContext`**: {project_context}
        2.  **`foundationalDocumentSummaries`**: {sow_and_proposal_summaries}

        YOUR TASK:
        Synthesize the provided `projectContext` and `foundationalDocumentSummaries` into a clear, professional "Mission & Approach" section. Your output MUST be a single, clean JSON object.

        SPECIFIC INSTRUCTIONS & TONE:
        *   **Tone:** Your writing style must be that of a senior consultant briefing a new team member: clear, confident, professional, and direct.
        *   **Synthesis, Not Repetition:** Do not just copy and paste information from the summaries. Synthesize the most critical points into a coherent narrative. For example, if multiple documents mention the same objective, distill it into one clear statement.
        *   **Focus on the "What" and "When":** This section is about the project's official mandate and high-level plan.

        JSON OUTPUT STRUCTURE AND CONTENT REQUIREMENTS:

        You MUST generate a JSON object with the following three keys:

        1.  **`projectMandate`**:
            *   **Content:** Generate a single, well-crafted paragraph (2-4 sentences) that clearly and concisely states the core client challenge and our mandated objective for the engagement.
            *   **Source:** Synthesize this from `projectContext.primaryProjectObjectives` and the `stated_client_problem_summary` and `project_objectives_stated_list` fields from the metadata of the provided SoW/Proposal summaries.

        2.  **`keyProjectPhases`**:
            *   **Content:** Generate a list of 2-4 objects, where each object represents a major phase of the project.
            *   **Source:** Synthesize this from the `project_phases_timeline_summary` and `key_milestones_or_deadlines_list` fields in the document metadata, as well as the overall structure of any Project Plan documents.
            *   **Object Structure:** Each object in the list must have the following keys:
                *   `phaseName`: A string with the name of the phase (e.g., "Phase 1: As-Is Analysis & Benchmarking").
                *   `phaseObjective`: A brief string describing the goal of that phase (e.g., "To understand the current state and identify key performance gaps.").
                *   `targetCompletionDate`: A string with the target end date for that phase (e.g., "Ends July 31, 2025"). If a specific date isn't available, state the quarter (e.g., "Ends Q3 2025").

        3.  **`coreAnalyticalWorkstreams`**:
            *   **Content:** Generate a list of 2-4 strings describing the main types of analysis the team will be conducting throughout the project.
            *   **Source:** Infer these workstreams from the `scope_in_list`, `key_deliverables_list`, and the overall content of the provided summaries. Look for recurring analytical themes.
            *   **Example Strings:** "Market Sizing & Competitive Positioning," "Operational Process Optimization & Cost-Benefit Analysis," "Financial Modeling & Business Case Development."
        """

        try:
            response = self.model.generate_content(prompt)
            return json.loads(response.text)
        except Exception as e:
            self.logger.error(f"Error synthesizing 'Mission & Approach' section: {e}")
            return {}

    def _synthesize_strategic_intelligence_readout(self, document_summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Synthesizes the 'Strategic Intelligence Readout' section of the onboarding guide.
        """
        self.logger.info("Synthesizing 'Strategic Intelligence Readout' section")

        # Group summaries by source type
        summaries_by_source_type = {}
        for summary in document_summaries:
            source_type = summary.get("document_source_type", "Unknown")
            if source_type not in summaries_by_source_type:
                summaries_by_source_type[source_type] = []
            summaries_by_source_type[source_type].append(summary)

        strategic_intelligence_readout = {}
        for source_type, summaries in summaries_by_source_type.items():
            prompt = f"""
            You are an expert Giani.ai AI Strategist, acting as a senior consultant. Your task is to analyze a collection of document summaries from a single category (e.g., all client-provided documents) and distill the most critical, overarching intelligence from them. The output must be a high-level synthesis, not just a list of individual document facts.

            CONTEXT PROVIDED:
            You will be given two key pieces of information for a specific project:

            1.  **`documentSourceType`**: "{source_type}"
            2.  **`documentSummariesForType`**: {summaries}

            YOUR TASK:
            Synthesize the provided `documentSummariesForType` into a single, cohesive "Intelligence Readout" for the specified `documentSourceType`. Your output MUST be a single, clean JSON object.

            SPECIFIC INSTRUCTIONS & TONE:
            *   **Tone:** Your writing style must be that of a senior consultant briefing a new team member: insightful, analytical, and focused on strategic relevance.
            *   **Cross-Document Synthesis:** Your primary goal is to **find the patterns, common themes, and most critical overarching points across ALL the provided document summaries.** Do not just pick one document; synthesize the collective intelligence.
            *   **Focus on the "Why":** Why is this category of information important for the project? What does it collectively tell us?

            JSON OUTPUT STRUCTURE AND CONTENT REQUIREMENTS:

            You MUST generate a JSON object with the following two keys:

            1.  **`comprehensiveSummary`**:
                *   **Content:** Generate a single, well-crafted paragraph (3-5 sentences) that provides a **holistic summary of the key intelligence** contained within this entire group of documents. This should be a true synthesis.
                *   **Example (for "Client-Provided Material"):** "Client documents consistently highlight a primary concern with market share erosion in their core technology segments while simultaneously showing a strong executive appetite for aggressive growth into new verticals. The client has mandated a comprehensive strategic review to identify $15M in cost savings and has emphasized that digital transformation is seen as a critical competitive differentiator for improving operational efficiency and customer experience."
                *   **Source:** Synthesize this from the `ai_high_level_narrative_summary` and key metadata fields (like `project_objectives_stated_list`, `client_requirements_or_pain_points_expressed_list`) across ALL documents in the `documentSummariesForType` list.

            2.  **`keyTakeaways`**:
                *   **Content:** Generate a list of 3-5 distinct, critical, and standalone bullet points. Each takeaway should represent a crucial fact, finding, or directive that a consultant **must know** from this category of documents.
                *   **Example (for "Client-Provided Material"):**
                    *   "The project is officially mandated to identify $15M in actionable cost savings."
                    *   "A 5-year growth strategy targeting 25% market expansion is the primary definition of success."
                    *   "Client feedback strongly indicates dissatisfaction with the current customer service response times."
                *   **Source:** Distill the most important and frequently mentioned points from the `ai_key_takeaways_bullets` and `extracted_metadata` of ALL documents in the `documentSummariesForType` list.
            """

            try:
                response = self.model.generate_content(prompt)
                strategic_intelligence_readout[source_type] = json.loads(response.text)
            except Exception as e:
                self.logger.error(f"Error synthesizing 'Strategic Intelligence Readout' for source type '{source_type}': {e}")
                strategic_intelligence_readout[source_type] = {}

        return strategic_intelligence_readout

    def _identify_priority_reading_list(self, document_summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Identifies the 'Priority Reading List' section of the onboarding guide.
        """
        self.logger.info("Identifying 'Priority Reading List' section")

        document_list = [
            {
                "filename": s.get("document_filename"),
                "documentSourceType": s.get("document_source_type"),
                "ai_overall_key_themes_list": s.get("key_themes"),
                "summary_snippet": (s.get("narrative_summary")[0] if s.get("narrative_summary") else "")[:200],
            }
            for s in document_summaries
        ]

        prompt = f"""
        You are an expert Giani.ai AI Strategist, acting as a seasoned Engagement Manager on a consulting project. Your critical task is to review a list of all available project documents and create a prioritized reading list for a new team member who needs to get up to speed as quickly and effectively as possible. Your prioritization must be strategic, logical, and clearly justified.

        CONTEXT PROVIDED:
        You will be given a JSON list of all processed documents for the project. Each document object in the list contains the following key metadata:
        *   `documentId`: A unique identifier for the document.
        *   `filename`: The original name of the document.
        *   `documentSourceType`: The user-validated category, like "SoW / Proposal Document", "Client Strategy Deck", "Meeting Artifacts", "Internal Research & Analysis".
        *   `summarySnippet`: A concise, high-level summary of the document's content.
        *   `keyThemes`: A list of the main themes covered in the document.
        *   `userNoteOnPurpose`: The original note provided by the user about the document's purpose.

        YOUR TASK:
        Based on the provided list of all project documents and their metadata, analyze the entire set and select a curated subset for a new team member's reading list. You must categorize your selections into two distinct tiers: "High-Priority ('Must-Reads')" and "Medium-Priority ('Should-Reads')". For every document you select, you must provide a concise, one-sentence justification for its inclusion and priority.

        Your output MUST be a single, clean JSON object.

        PRIORITIZATION CRITERIA (How to think like an Engagement Manager):
        You must use the following criteria to determine a document's priority level.

        **High-Priority ("Must-Read") documents are typically:**
        *   **Foundational & Scoping:** Documents that define the project's entire purpose, scope, and mandate (e.g., `Statement of Work (SoW)`, `Proposal Document`, `Client Brief/RFP`).
        *   **Core Strategy:** The primary strategic documents provided by the client or developed by the team that form the basis of the analysis (e.g., `Client Strategy Deck`).
        *   **Key Decisions:** The most recent, critical `Meeting Artifacts` that document major go/no-go decisions or significant changes in project direction.

        **Medium-Priority ("Should-Read") documents are typically:**
        *   **Supporting Analysis:** Key research and analysis documents that provide the evidence for the strategy (e.g., `Market Sizing Model`, `Competitive Landscape Analysis`, `External Third-Party Research`).
        *   **Detailed Plans:** Documents that outline the "how" (e.g., `Project Plan / Timeline`).
        *   **Recent Context:** Important but not foundational `Meeting Artifacts` that provide recent context on progress.
        *   **Past Learnings:** `Past Similar Project References` that offer useful context or templates.

        **Justification Requirement:**
        Your one-sentence justification for each document ("Reason for Priority") must be specific and helpful.
        *   **Bad Justification:** "This document is important."
        *   **Good Justification:** "This SoW document outlines the official project scope, key deliverables, and timeline agreed upon with the client." OR "This market analysis report contains the key data that supports our core hypothesis."

        JSON OUTPUT STRUCTURE AND CONTENT REQUIREMENTS:

        You MUST generate a JSON object with a single key, `priorityReadingList`, which contains two keys: `highPriority` and `mediumPriority`.

        1.  **`highPriority`**:
            *   **Content:** A list containing **2 to 4** document objects. Do not select more than 4 for this category.
            *   **Object Structure:** Each object in the list must have the following keys:
                *   `documentId`: The original `documentId` from the input.
                *   `filename`: The original `filename` from the input.
                *   `documentSourceType`: The `documentSourceType` from the input.
                *   `reasonForPriority`: Your concise, one-sentence justification for why this document is a "Must-Read."

        2.  **`mediumPriority`**:
            *   **Content:** A list containing **4 to 6** document objects.
            *   **Object Structure:** Each object must have the same keys as the `highPriority` objects (`documentId`, `filename`, `documentSourceType`, `reasonForPriority`).
        
        Document List:
        {document_list}
        """

        try:
            response = self.model.generate_content(prompt)
            return json.loads(response.text)
        except Exception as e:
            self.logger.error(f"Error identifying 'Priority Reading List': {e}")
            return {}

    def _generate_knowledge_base_faq(self, document_summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Generates the 'Knowledge Base FAQ' section of the onboarding guide.
        """
        self.logger.info("Generating 'Knowledge Base FAQ' section")

        curated_project_insights = {
            "projectObjectives": list(set(o for s in document_summaries for o in s.get("extracted_metadata", {}).get("project_objectives_stated_list", []))),
            "keyClientRequirementsAndConcerns": list(set(c for s in document_summaries for c in s.get("extracted_metadata", {}).get("client_requirements_or_pain_points_expressed_list", []))),
            "keyFindingsFromResearch": list(set(f for s in document_summaries for f in s.get("extracted_metadata", {}).get("core_analytical_findings_insights_list", []))),
            "keyDecisionsAndActionItems": list(set(d["decision"] for s in document_summaries for d in s.get("extracted_metadata", {}).get("key_decisions_made_list_of_objects", []))),
            "keyIdentifiedRisks": list(set(r["risk"] for s in document_summaries for r in s.get("extracted_metadata", {}).get("key_risks_issues_status_list_of_objects", []))),
            "keyLearningsFromPastProjects": [],  # This would need to be populated from a different source
            "documentIndex": {s["document_id"]: {"filename": s["document_filename"], "documentSourceType": s["document_source_type"]} for s in document_summaries},
        }

        prompt = f"""
        You are an expert Giani.ai AI Strategist, acting as a highly experienced Consulting Partner. Your task is to review a curated list of key findings and insights from an entire project knowledge base and proactively identify the most strategic questions a new consultant would (or should) have. You must then synthesize concise, evidence-based answers to these questions.

        CONTEXT PROVIDED:
        You will be given a `curatedProjectInsights` JSON object containing a distilled collection of the most critical facts, findings, objectives, and risks from across ALL processed documents in the project. This is your "briefing packet." The structure will be:
        *   `projectObjectives`: A list of the core project goals.
        *   `keyClientRequirementsAndConcerns`: A list of the client's main stated needs or worries.
        *   `keyFindingsFromResearch`: A list of the most important analytical findings from internal/external research.
        *   `keyDecisionsAndActionItems`: A list of critical decisions made and key action items from meetings.
        *   `keyIdentifiedRisks`: A list of the most significant identified project risks.
        *   `keyLearningsFromPastProjects`: A list of relevant lessons from past work, if applicable.
        *   `documentIndex`: A simple mapping of `documentId` to `filename` and `documentSourceType` for citation purposes.

        YOUR TASK:
        Based ONLY on the provided `curatedProjectInsights`, your task is twofold:
        1.  **Generate a list of 3-5 highly strategic, frequently asked questions** that a consultant reviewing this project would need answered to be effective.
        2.  For each question you generate, **synthesize a concise, direct answer** using only the information available in the `curatedProjectInsights`.

        Your output MUST be a single, clean JSON object.

        INSTRUCTIONS FOR QUESTION GENERATION:
        *   **Think Like a Partner:** Your questions should not be simple factual lookups. They should be strategic. Ask "why" and "so what."
        *   **Focus on Key Levers:** Frame questions around the most critical aspects of a consulting project: Strategy, Risk, Client Management, and Value Delivery.
        *   **Synthesize, Don't Invent:** The questions must be answerable using the provided `curatedProjectInsights`.
        *   **Examples of Good Strategic Questions:**
            *   "What are the primary data points supporting our core recommendation?"
            *   "Are there any conflicting perspectives between what the client asked for and what our research suggests?"
            *   "What is the most critical risk to the project timeline and how is it being mitigated?"
            *   "Based on past projects, what is the single most important lesson we should apply here?"

        INSTRUCTIONS FOR ANSWER SYNTHESIS:
        *   **Be Direct & Concise:** Provide a 2-4 sentence answer for each question. Get straight to the point.
        *   **Synthesize Across Sources:** Your answer should combine information from different parts of the `curatedProjectInsights` if necessary to form a complete picture.
        *   **Cite Your Sources:** For each key piece of information in your answer, you MUST cite the likely `documentSourceType` where that information would be found, based on the nature of the insight. Use parentheses for citations, e.g., (SoW / Proposal Document). If multiple source types contribute, cite the most direct one.
        *   **Grounding:** All answers must be directly supported by the provided `curatedProjectInsights`. Do not introduce external information or make assumptions.

        JSON OUTPUT STRUCTURE AND CONTENT REQUIREMENTS:

        You MUST generate a JSON object with a single key, `knowledgeFAQ`, which contains a list of 3-5 Q&A objects.

        *   **`knowledgeFAQ`**:
            *   **Content:** A list containing **3 to 5** question-and-answer objects.
            *   **Object Structure:** Each object in the list must have the following two keys:
                *   `question`: Your AI-generated strategic question (string).
                *   `answer`: Your AI-synthesized, cited answer to that question (string).
        
        Curated Project Insights:
        {curated_project_insights}
        """

        try:
            response = self.model.generate_content(prompt)
            return json.loads(response.text)
        except Exception as e:
            self.logger.error(f"Error generating 'Knowledge Base FAQ': {e}")
            return {}

    def _get_distribution_by_source(self, document_summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Calculates the distribution of documents by source type.
        """
        source_counts = {}
        for summary in document_summaries:
            source_type = summary.get("document_source_type", "Unknown")
            source_counts[source_type] = source_counts.get(source_type, 0) + 1

        total_documents = len(document_summaries)
        distribution = [
            {
                "sourceType": source_type,
                "percentage": round((count / total_documents) * 100),
            }
            for source_type, count in source_counts.items()
        ]
        return distribution

    def _format_strategic_intelligence_readout(self, strategic_intelligence_readout: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Formats the strategic intelligence readout to match the API contract.
        """
        formatted_readout = []
        for source_type, data in strategic_intelligence_readout.items():
            formatted_readout.append(
                {
                    "sourceType": source_type,
                    "comprehensiveSummary": data.get("summary"),
                    "keyTakeaways": data.get("key_takeaways"),
                }
            )
        return formatted_readout
