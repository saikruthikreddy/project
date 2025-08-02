"""
Service for generating the Project Onboarding Guide.
Improved version with parallel processing, better error handling, and optimized database queries.
"""

import logging
import json
import asyncio
import os
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import time

from giani_pkb.database.database_manager import DatabaseManager
from giani_pkb.utils.config import GEMINI_API_KEY, LLM_CONFIG
from giani_pkb.utils.gemini_client import initialize_gemini_client
import google.generativeai as genai

PROMPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "prompts"))

class OnboardingGuideGenerator:
    """
    Orchestrates the generation of the Project Onboarding Guide with improved performance and error handling.
    """

    def __init__(self, db_manager: DatabaseManager, gemini_api_key: Optional[str] = None, model_config: Optional[Dict] = None):
        self.logger = logging.getLogger(__name__)
        self.db_manager = db_manager
        self.gemini_api_key = gemini_api_key or GEMINI_API_KEY
        
        # Load model configuration from config or use defaults
        self.model_config = model_config or getattr(LLM_CONFIG, 'ONBOARDING_GUIDE', {
            'primary_model': 'gemini-1.5-pro',
            'fallback_model': 'gemini-pro',
            'max_retries': 3,
            'timeout': 30
        })
        
        if not self.gemini_api_key:
            raise ValueError("Gemini API key must be provided.")
        
        initialize_gemini_client(self.gemini_api_key)
        self.model = genai.GenerativeModel(self.model_config['primary_model'])
        self.fallback_model = genai.GenerativeModel(self.model_config['fallback_model'])
        
        # Load prompts from files
        self.prompts = self._load_prompts()

    def _load_prompts(self) -> Dict[str, str]:
        """Load prompts from the prompts directory."""
        prompts = {}
        prompt_files = {
            'mission_and_approach': 'mission_and_approach_prompt.txt',
            'strategic_intelligence_readout': 'strategic_intelligence_readout_prompt.txt',
            'priority_reading_list': 'priority_reading_list_prompt.txt',
            'knowledge_base_faq': 'knowledge_base_faq_prompt.txt'
        }
        
        for key, filename in prompt_files.items():
            file_path = os.path.join(PROMPTS_DIR, filename)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    prompts[key] = f.read().strip()
                self.logger.info(f"Loaded prompt: {key}")
            except FileNotFoundError:
                self.logger.warning(f"Prompt file not found: {file_path}, using fallback")
                prompts[key] = self._get_fallback_prompt(key)
            except Exception as e:
                self.logger.error(f"Error loading prompt {key}: {e}")
                prompts[key] = self._get_fallback_prompt(key)
        
        return prompts

    def _get_fallback_prompt(self, prompt_type: str) -> str:
        """Provide fallback prompts if files are not found."""
        fallback_prompts = {
            'mission_and_approach': """
You are a Giani.ai AI Strategist, acting as an experienced Engagement Manager. Your task is to distill foundational project documents into a clear and concise "Mission & Approach" briefing for a new consultant joining the team.

CONTEXT PROVIDED:
{lean_context}

YOUR TASK:
Synthesize the provided context into a clear, professional "Mission & Approach" section. Your output MUST be a single, clean JSON object with keys: projectMandate, keyProjectPhases, and strategicApproach.
""",
            'strategic_intelligence_readout': """
You are an expert Giani.ai AI Strategist. Analyze document summaries from source type "{source_type}" and create an intelligence readout.

CONTEXT PROVIDED:
{lean_context}

YOUR TASK:
Generate a JSON object with keys: comprehensiveSummary, keyTakeaways, and keyThemes.
""",
            'priority_reading_list': """
You are an expert Giani.ai AI Strategist. Create a prioritized reading list for a new team member.

CONTEXT PROVIDED:
{document_context}

YOUR TASK:
Generate a JSON object with key `priorityReadingList` containing highPriority and mediumPriority document lists.
""",
            'knowledge_base_faq': """
You are an expert Giani.ai AI Strategist. Generate strategic Q&A pairs for a project knowledge FAQ.

CURATED PROJECT INSIGHTS:
{curated_insights}

YOUR TASK:
Generate a JSON object with key `knowledgeFAQ` containing 3-5 strategic question-answer pairs.
"""
        }
        return fallback_prompts.get(prompt_type, "Default prompt not available.")

    def generate_onboarding_guide(self, project_id: int) -> Dict[str, Any]:
        """
        Generates the project onboarding guide for a given project_id with parallel processing.
        """
        start_time = time.time()
        self.logger.info(f"Generating onboarding guide for project_id: {project_id}")

        try:
            # Step 1: Data Aggregation (Sequential - these depend on each other)
            project_context = self._get_project_context(project_id)
            document_summaries = self._get_document_summaries_optimized(project_id)

            if not document_summaries:
                self.logger.warning(f"No document summaries found for project_id: {project_id}")
                return self._create_empty_guide(project_context)

            # Step 2: AI-Powered Synthesis (Parallel - these are independent)
            synthesis_results = self._run_parallel_synthesis(project_context, document_summaries)

            # Step 3: Data Aggregation & Assembly - FIXED to match LLM outputs
            mission_and_approach = synthesis_results.get("mission_and_approach", {})
            priority_reading = synthesis_results.get("priority_reading_list", {})
            knowledge_faq = synthesis_results.get("knowledge_base_faq", {})
            
            onboarding_guide = {
                "projectName": project_context.get("name", "Unknown Project"),
                "lastSynthesized": datetime.utcnow().isoformat() + "Z",
                "missionAndApproach": {
                    "projectMandate": mission_and_approach.get("projectMandate", ""),
                    "keyProjectPhases": mission_and_approach.get("keyProjectPhases", []),
                    "coreAnalyticalWorkstreams": mission_and_approach.get("strategicApproach", [])  # Fixed mapping
                },
                "knowledgeAtAGlance": {
                    "documentsProcessed": len(document_summaries),
                    "keyThemesIdentified": len(set(theme for s in document_summaries for theme in s.get("key_themes", []))),
                    "mustReadDocuments": len(priority_reading.get("priorityReadingList", {}).get("highPriority", [])),
                    "distributionBySource": self._get_distribution_by_source(document_summaries),
                },
                "strategicIntelligenceReadout": self._format_strategic_intelligence_readout(
                    synthesis_results.get("strategic_intelligence_readout", {})
                ),
                "priorityReadingList": priority_reading.get("priorityReadingList", {"highPriority": [], "mediumPriority": []}),
                "knowledgeFAQ": knowledge_faq.get("knowledgeFAQ", []),
            }

            # Add synthesis status for debugging
            onboarding_guide["synthesisStatus"] = {
                "totalTime": round(time.time() - start_time, 2),
                "errors": synthesis_results.get("errors", {}),
                "successfulSections": [k for k, v in synthesis_results.items() if k != "errors" and v]
            }

            self.logger.info(f"Onboarding guide generated successfully in {onboarding_guide['synthesisStatus']['totalTime']}s")
            return onboarding_guide

        except Exception as e:
            self.logger.error(f"Fatal error generating onboarding guide for project_id {project_id}: {e}")
            return {
                "error": "Failed to generate onboarding guide",
                "details": str(e),
                "projectName": project_context.get("name", "Unknown Project") if 'project_context' in locals() else "Unknown Project",
                "lastSynthesized": datetime.utcnow().isoformat() + "Z"
            }

    def _safe_synthesis_call(self, func, task_name: str, *args) -> Dict[str, Any]:
        """
        Safely executes a synthesis function with retry logic and error handling.
        """
        max_retries = self.model_config.get('max_retries', 3)
        
        for attempt in range(max_retries):
            try:
                result = func(*args)
                if result:  # Non-empty result
                    return {"success": True, "data": result}
                else:
                    self.logger.warning(f"{task_name} returned empty result on attempt {attempt + 1}")
            except json.JSONDecodeError as e:
                self.logger.warning(f"{task_name} JSON decode error on attempt {attempt + 1}: {e}")
                if attempt == max_retries - 1:
                    return {"success": False, "error": f"JSON decode failed after {max_retries} attempts: {str(e)}"}
            except Exception as e:
                self.logger.warning(f"{task_name} failed on attempt {attempt + 1}: {e}")
                if attempt == max_retries - 1:
                    return {"success": False, "error": f"Failed after {max_retries} attempts: {str(e)}"}
            
            # Wait before retry
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
        
        return {"success": False, "error": f"All {max_retries} attempts failed"}

    def _run_parallel_synthesis(self, project_context: Dict[str, Any], document_summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Runs all synthesis tasks in parallel using ThreadPoolExecutor.
        """
        synthesis_results = {"errors": {}}
        
        # Define synthesis tasks
        tasks = {
            "mission_and_approach": (self._synthesize_mission_and_approach, project_context, document_summaries),
            "strategic_intelligence_readout": (self._synthesize_strategic_intelligence_readout, document_summaries),
            "priority_reading_list": (self._identify_priority_reading_list, document_summaries),
            "knowledge_base_faq": (self._generate_knowledge_base_faq, document_summaries)
        }

        # Execute tasks in parallel
        with ThreadPoolExecutor(max_workers=4) as executor:
            # Submit all tasks
            future_to_task = {}
            for task_name, (func, *args) in tasks.items():
                future = executor.submit(self._safe_synthesis_call, func, task_name, *args)
                future_to_task[future] = task_name

            # Collect results as they complete
            for future in as_completed(future_to_task):
                task_name = future_to_task[future]
                try:
                    result = future.result()
                    if result.get("success"):
                        synthesis_results[task_name] = result["data"]
                    else:
                        synthesis_results["errors"][task_name] = result["error"]
                        self.logger.error(f"Task {task_name} failed: {result['error']}")
                except Exception as e:
                    synthesis_results["errors"][task_name] = str(e)
                    self.logger.error(f"Task {task_name} raised exception: {e}")

        return synthesis_results

    def _format_strategic_intelligence_readout(self, strategic_intelligence_readout: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Formats the strategic intelligence readout to match the API contract.
        """
        formatted_readout = []
        for source_type, data in strategic_intelligence_readout.items():
            formatted_readout.append({
                "sourceType": source_type,
                "comprehensiveSummary": data.get("comprehensiveSummary", ""),
                "keyTakeaways": data.get("keyTakeaways", []),
                "keyThemes": data.get("keyThemes", [])  # Added keyThemes from LLM output
            })
        return formatted_readout

    def _create_empty_guide(self, project_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Creates an empty guide structure when no documents are available.
        """
        return {
            "projectName": project_context.get("name", "Unknown Project"),
            "lastSynthesized": datetime.utcnow().isoformat() + "Z",
            "missionAndApproach": {
                "projectMandate": "No project documents available for analysis.",
                "keyProjectPhases": [],
                "coreAnalyticalWorkstreams": [],
            },
            "knowledgeAtAGlance": {
                "documentsProcessed": 0,
                "keyThemesIdentified": 0,
                "mustReadDocuments": 0,
                "distributionBySource": [],
            },
            "strategicIntelligenceReadout": [],
            "priorityReadingList": {"highPriority": [], "mediumPriority": []},
            "knowledgeFAQ": [],
            "synthesisStatus": {
                "totalTime": 0,
                "errors": {"general": "No documents available"},
                "successfulSections": []
            }
        }

    # Keep all other existing methods unchanged
    def _get_project_context(self, project_id: int) -> Dict[str, Any]:
        """Retrieves project context from the database."""
        self.logger.info(f"Getting project context for project_id: {project_id}")
        try:
            project = self.db_manager.get_project(project_id)
            if project:
                return project.to_dict_detailed()
        except Exception as e:
            self.logger.error(f"Error getting project context: {e}")
        return {}

    def _get_document_summaries_optimized(self, project_id: int) -> List[Dict[str, Any]]:
        """Retrieves document summaries from the database in a single optimized query."""
        self.logger.info(f"Getting document summaries for project_id: {project_id}")
        try:
            # Use optimized method that gets all summaries in one query
            if hasattr(self.db_manager, 'get_all_summaries_for_project'):
                summaries = self.db_manager.get_all_summaries_for_project(project_id)
            else:
                # Fallback to original method if optimized version doesn't exist yet
                self.logger.warning("Using fallback method for document summaries - consider implementing get_all_summaries_for_project")
                documents = self.db_manager.get_project_documents(project_id)
                summaries = []
                for doc in documents:
                    summary = self.db_manager.get_document_summary(doc.id)
                    if summary:
                        summaries.append(summary)
            return summaries
        except Exception as e:
            self.logger.error(f"Error getting document summaries: {e}")
            return []

    def _create_lean_context_for_mission(self, project_context: Dict[str, Any], document_summaries: List[Dict[str, Any]]) -> str:
        """Creates a lean context string for mission and approach synthesis."""
        sow_and_proposal_summaries = [
            s for s in document_summaries
            if s.get("document_category") in ["SoW / Proposal Document", "Project Plan"]
        ]
        
        if not sow_and_proposal_summaries:
            return "No foundational documents available."
        
        context_parts = []
        context_parts.append(f"Project Context: {json.dumps(project_context, indent=2)}")
        
        for summary in sow_and_proposal_summaries:
            doc_context = f"""
Document: {summary.get('document_filename', 'Unknown')}
Category: {summary.get('document_category', 'Unknown')}
Problem Summary: {summary.get('extracted_metadata', {}).get('stated_client_problem_summary', 'N/A')}
Objectives: {summary.get('extracted_metadata', {}).get('project_objectives_stated_list', [])}
Timeline: {summary.get('extracted_metadata', {}).get('project_phases_timeline_summary', 'N/A')}
Milestones: {summary.get('extracted_metadata', {}).get('key_milestones_or_deadlines_list', [])}
Scope: {summary.get('extracted_metadata', {}).get('scope_in_list', [])}
Deliverables: {summary.get('extracted_metadata', {}).get('key_deliverables_list', [])}
"""
            context_parts.append(doc_context)
        
        return "\n".join(context_parts)

    def _create_lean_context_for_readout(self, summaries_for_type: List[Dict[str, Any]]) -> str:
        """Creates a lean context string for strategic intelligence readout."""
        context_parts = []
        for summary in summaries_for_type:
            doc_context = f"""
Document: {summary.get('document_filename', 'Unknown')}
Narrative: {summary.get('ai_high_level_narrative_summary', 'N/A')}
Key Takeaways: {summary.get('ai_key_takeaways_bullets', [])}
Objectives: {summary.get('extracted_metadata', {}).get('project_objectives_stated_list', [])}
Client Concerns: {summary.get('extracted_metadata', {}).get('client_requirements_or_pain_points_expressed_list', [])}
"""
            context_parts.append(doc_context)
        
        return "\n".join(context_parts)

    def _synthesize_mission_and_approach(self, project_context: Dict[str, Any], document_summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Synthesizes the 'Mission & Approach' section of the onboarding guide."""
        self.logger.info("Synthesizing 'Mission & Approach' section")

        lean_context = self._create_lean_context_for_mission(project_context, document_summaries)
        
        if "No foundational documents available" in lean_context:
            return {
                "projectMandate": "N/A",
                "keyProjectPhases": [],
                "strategicApproach": [],
            }

        # Use loaded prompt with context substitution
        prompt = self.prompts['mission_and_approach'].format(lean_context=lean_context)

        try:
            response = self.model.generate_content(prompt)
            result = json.loads(response.text)
            # Validate the structure
            if not all(key in result for key in ['projectMandate', 'keyProjectPhases', 'strategicApproach']):
                raise ValueError("LLM response missing required keys")
            return result
        except Exception as e:
            self.logger.error(f"Error synthesizing 'Mission & Approach' section: {e}")
            # Try fallback model
            try:
                response = self.fallback_model.generate_content(prompt)
                result = json.loads(response.text)
                if not all(key in result for key in ['projectMandate', 'keyProjectPhases', 'strategicApproach']):
                    raise ValueError("Fallback LLM response missing required keys")
                return result
            except Exception as fallback_error:
                self.logger.error(f"Fallback model also failed: {fallback_error}")
                # Return default structure
                return {
                    "projectMandate": "Unable to synthesize project mandate from available documents.",
                    "keyProjectPhases": [],
                    "strategicApproach": []
                }

    def _synthesize_strategic_intelligence_readout(self, document_summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Synthesizes the 'Strategic Intelligence Readout' section of the onboarding guide."""
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
            lean_context = self._create_lean_context_for_readout(summaries)
            
            # Use loaded prompt with context substitution
            prompt = self.prompts['strategic_intelligence_readout'].format(
                source_type=source_type,
                lean_context=lean_context
            )

            try:
                response = self.model.generate_content(prompt)
                result = json.loads(response.text)
                # Validate structure
                if not all(key in result for key in ['comprehensiveSummary', 'keyTakeaways', 'keyThemes']):
                    raise ValueError("LLM response missing required keys")
                strategic_intelligence_readout[source_type] = result
            except Exception as e:
                self.logger.error(f"Error synthesizing 'Strategic Intelligence Readout' for source type '{source_type}': {e}")
                strategic_intelligence_readout[source_type] = {
                    "comprehensiveSummary": f"Unable to synthesize intelligence for {source_type} documents.",
                    "keyTakeaways": [],
                    "keyThemes": []
                }

        return strategic_intelligence_readout

    def _identify_priority_reading_list(self, document_summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Identifies the 'Priority Reading List' section of the onboarding guide."""
        self.logger.info("Identifying 'Priority Reading List' section")

        # Create lean document list for prompt
        document_context = ""
        for i, s in enumerate(document_summaries):
            doc_info = f"""
Document {i+1}:
- Filename: {s.get("document_filename", "Unknown")}
- Source Type: {s.get("document_source_type", "Unknown")}
- Summary: {(s.get("narrative_summary", [""])[0] if s.get("narrative_summary") else "")[:200]}
- Key Themes: {", ".join(s.get("key_themes", [])[:5])}  # Limit to first 5 themes
"""
            document_context += doc_info

        # Use loaded prompt with context substitution
        prompt = self.prompts['priority_reading_list'].format(document_context=document_context)

        try:
            response = self.model.generate_content(prompt)
            result = json.loads(response.text)
            # Validate structure
            if "priorityReadingList" not in result:
                raise ValueError("LLM response missing priorityReadingList key")
            reading_list = result["priorityReadingList"]
            if not all(key in reading_list for key in ['highPriority', 'mediumPriority']):
                raise ValueError("priorityReadingList missing required keys")
            return result
        except Exception as e:
            self.logger.error(f"Error identifying 'Priority Reading List': {e}")
            return {"priorityReadingList": {"highPriority": [], "mediumPriority": []}}

    def _generate_knowledge_base_faq(self, document_summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generates the 'Knowledge Base FAQ' section of the onboarding guide."""
        self.logger.info("Generating 'Knowledge Base FAQ' section")

        # Create curated insights with limited data to avoid context overflow
        curated_insights = {
            "projectObjectives": list(set(o for s in document_summaries for o in s.get("extracted_metadata", {}).get("project_objectives_stated_list", [])))[:10],
            "keyClientConcerns": list(set(c for s in document_summaries for c in s.get("extracted_metadata", {}).get("client_requirements_or_pain_points_expressed_list", [])))[:10],
            "keyFindings": list(set(f for s in document_summaries for f in s.get("extracted_metadata", {}).get("core_analytical_findings_insights_list", [])))[:10],
            "keyDecisions": [d.get("decision", "") for s in document_summaries for d in s.get("extracted_metadata", {}).get("key_decisions_made_list_of_objects", []) if d.get("decision")][:10],
            "keyRisks": [r.get("risk", "") for s in document_summaries for r in s.get("extracted_metadata", {}).get("key_risks_issues_status_list_of_objects", []) if r.get("risk")][:10],
        }

        # Use loaded prompt with context substitution
        prompt = self.prompts['knowledge_base_faq'].format(
            curated_insights=json.dumps(curated_insights, indent=2)
        )

        try:
            response = self.model.generate_content(prompt)
            result = json.loads(response.text)
            # Validate structure
            if "knowledgeFAQ" not in result:
                raise ValueError("LLM response missing knowledgeFAQ key")
            return result
        except Exception as e:
            self.logger.error(f"Error generating 'Knowledge Base FAQ': {e}")
            return {"knowledgeFAQ": []}

    def _get_distribution_by_source(self, document_summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Calculates the distribution of documents by source type."""
        source_counts = {}
        for summary in document_summaries:
            source_type = summary.get("document_source_type", "Unknown")
            source_counts[source_type] = source_counts.get(source_type, 0) + 1

        total_documents = len(document_summaries)
        if total_documents == 0:
            return []
            
        distribution = [
            {
                "sourceType": source_type,
                "percentage": round((count / total_documents) * 100),
            }
            for source_type, count in source_counts.items()
        ]
        return distribution