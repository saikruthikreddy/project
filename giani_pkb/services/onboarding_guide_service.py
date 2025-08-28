"""
Service for generating the Project Onboarding Guide.
Improved version with parallel processing, better error handling, and optimized database queries.
Updated to return document UUIDs instead of integer IDs.
Updated to work with new DocumentSummary model structure.
Fixed to handle None values in list fields properly.
"""
import logging
import json
import asyncio
import os
import re
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import time
from giani_pkb.database.database_manager import DatabaseManager
from giani_pkb.utils.config import GEMINI_API_KEY
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
        self.model_config = model_config or {
            'primary_model': 'gemini-1.5-pro',
            'fallback_model': 'gemini-pro',
            'max_retries': 3,
            'timeout': 30
        }
        
        if not self.gemini_api_key:
            raise ValueError("Gemini API key must be provided.")
        
        initialize_gemini_client(self.gemini_api_key)
        
        # Configure generation config to force JSON output
        generation_config = genai.types.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.1,
            top_p=0.8,
            top_k=40,
            max_output_tokens=4096,
        )
        
        self.model = genai.GenerativeModel(
            self.model_config['primary_model'],
            generation_config=generation_config
        )
        
        self.fallback_model = genai.GenerativeModel(
            self.model_config['fallback_model'],
            generation_config=generation_config
        )
        
        # Load prompts from files
        self.prompts = self._load_prompts()
    
    def _safe_get_list(self, data: Dict[str, Any], key: str, default: List = None) -> List:
        """Safely get a list value from a dictionary, handling None values."""
        if default is None:
            default = []
        value = data.get(key, default)
        return value if value is not None else default
    
    def _safe_get_string(self, data: Dict[str, Any], key: str, default: str = "") -> str:
        """Safely get a string value from a dictionary, handling None values."""
        value = data.get(key, default)
        return value if value is not None else default
    
    def _load_prompts(self) -> Dict[str, str]:
        """Load prompts from the prompts directory."""
        prompts = {}
        prompt_files = {
            'mission_and_approach': 'mission_and_approach_prompt.txt',
            'strategic_intelligence_readout': 'strategic_intelligence_readout_prompt.txt',
            'priority_reading_list': 'priority_reading_list_prompt.txt',
            'knowledge_base_faq': 'knowledge_base_faq_prompt.txt'
        }
        
        # Load prompts from files
        for key, filename in prompt_files.items():
            file_path = os.path.join(PROMPTS_DIR, filename)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    prompts[key] = f.read().strip()
                self.logger.info(f"Loaded prompt: {key}")
            except FileNotFoundError:
                self.logger.error(f"Prompt file not found: {file_path}")
                raise FileNotFoundError(f"Required prompt file not found: {file_path}")
            except Exception as e:
                self.logger.error(f"Error loading prompt {key}: {e}")
                raise
        
        return prompts
    
    def _validate_response_completeness(self, response_text: str, expected_keys: List[str]) -> bool:
        """Check if response appears complete before parsing."""
        if not response_text or len(response_text.strip()) < 10:
            return False
        
        # Check for common truncation patterns
        truncation_patterns = [
            r'^\s*"[^"]*"?\s*$',  # Just a key name
            r'^\s*\{\s*"[^"]*"?\s*$',  # Incomplete object start
            r'^\s*\[\s*$',  # Just opening bracket
        ]
        
        for pattern in truncation_patterns:
            if re.match(pattern, response_text.strip()):
                return False
        
        return True
    
    def _clean_json_response(self, response_text: str) -> str:
        """Clean and prepare JSON response from LLM."""
        # Remove leading/trailing whitespace and newlines
        cleaned = response_text.strip()
        
        # Handle specific truncated response patterns
        if cleaned == '"knowledgeFAQ"' or cleaned.startswith('\n  "knowledgeFAQ"') or cleaned == '"knowledgeFAQ"':
            self.logger.warning("Detected truncated FAQ response, returning empty structure")
            return '{"knowledgeFAQ": []}'
        
        # Remove markdown code blocks if present
        if cleaned.startswith('```json'):
            cleaned = cleaned.replace('```json', '').replace('```', '').strip()
        elif cleaned.startswith('```'):
            cleaned = cleaned.replace('```', '').strip()
        
        # Remove leading quotes if present and not part of JSON structure
        if cleaned.startswith('"') and not cleaned.startswith('{"'):
            cleaned = cleaned.strip('"')
        
        # Remove any leading newlines or whitespace again
        cleaned = cleaned.strip()
        
        # Ensure proper JSON structure
        if not cleaned.startswith('{') and not cleaned.startswith('['):
            # Try to find JSON object in the response
            json_match = re.search(r'(\{.*\}|$$.*$$)', cleaned, re.DOTALL)
            if json_match:
                cleaned = json_match.group(1)
            else:
                # If no JSON found, try to wrap it based on expected content
                if 'knowledgeFAQ' in cleaned or 'FAQ' in cleaned:
                    cleaned = '{"knowledgeFAQ": []}'
                elif 'priorityReadingList' in cleaned:
                    cleaned = '{"priorityReadingList": {"highPriority": [], "mediumPriority": []}}'
                else:
                    cleaned = '{}'
        
        return cleaned
    
    def _safe_json_parse(self, response_text: str) -> Dict[str, Any]:
        """Safely parse JSON response with fallback handling."""
        try:
            cleaned_response = self._clean_json_response(response_text)
            self.logger.debug(f"Cleaned JSON response: {cleaned_response[:200]}...")
            return json.loads(cleaned_response)
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON parsing failed: {e}")
            self.logger.error(f"Raw response: {response_text[:500]}...")  # Log first 500 chars
            self.logger.error(f"Cleaned response: {cleaned_response[:500]}...")
            raise
    
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
            
            # Safe theme extraction with None handling
            all_themes = set()
            for s in document_summaries:
                if s is not None:
                    themes = self._safe_get_list(s, "key_themes")
                    all_themes.update(themes)
            
            onboarding_guide = {
                "projectName": project_context.get("name", "Unknown Project"),
                "lastSynthesized": datetime.utcnow().isoformat() + "Z",
                "missionAndApproach": {
                    "projectMandate": mission_and_approach.get("projectMandate", ""),
                    "keyProjectPhases": self._safe_get_list(mission_and_approach, "keyProjectPhases"),
                    "coreAnalyticalWorkstreams": self._safe_get_list(mission_and_approach, "strategicApproach")
                },
                "knowledgeAtAGlance": {
                    "documentsProcessed": len([s for s in document_summaries if s is not None]),
                    "keyThemesIdentified": len(all_themes),
                    "mustReadDocuments": len(self._safe_get_list(priority_reading.get("priorityReadingList", {}), "highPriority")),
                    "distributionBySource": self._get_distribution_by_source(document_summaries),
                },
                "strategicIntelligenceReadout": self._format_strategic_intelligence_readout(
                    synthesis_results.get("strategic_intelligence_readout", {})
                ),
                "priorityReadingList": priority_reading.get("priorityReadingList", {"highPriority": [], "mediumPriority": []}),
                "knowledgeFAQ": self._safe_get_list(knowledge_faq, "knowledgeFAQ"),
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
            if data is not None:
                formatted_readout.append({
                    "sourceType": source_type,
                    "comprehensiveSummary": self._safe_get_string(data, "comprehensiveSummary"),
                    "keyTakeaways": self._safe_get_list(data, "keyTakeaways"),
                    "keyThemes": self._safe_get_list(data, "keyThemes")
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
            self.logger.warning("Using fallback method for document summaries - consider implementing get_all_summaries_for_project")
            documents = self.db_manager.get_project_documents(project_id)
            summaries = []
            
            for doc in documents:
                summary = self.db_manager.get_document_summary(doc.id)
                if summary:
                    summaries.append(summary)
            
            # Convert summaries to dict format and ensure document_id is UUID string
            formatted_summaries = []
            for summary in summaries:
                if summary is None:
                    continue
                    
                if hasattr(summary, 'to_dict'):
                    summary_dict = summary.to_dict()
                else:
                    summary_dict = summary
                
                # Ensure document_id is the UUID, not integer id
                if hasattr(summary, 'document_id'):
                    summary_dict['document_id'] = str(summary.document_id)
                elif 'document_id' in summary_dict:
                    # Convert to string if it's a UUID object
                    summary_dict['document_id'] = str(summary_dict['document_id'])
                
                # Ensure all list fields are never None
                list_fields = ['key_themes', 'key_takeaways', 'extracted_keywords', 
                              'key_people_mentioned', 'key_organizations_mentioned', 
                              'key_dates_mentioned']
                
                for field in list_fields:
                    if summary_dict.get(field) is None:
                        summary_dict[field] = []
                
                formatted_summaries.append(summary_dict)
            
            return formatted_summaries
            
        except Exception as e:
            self.logger.error(f"Error getting document summaries: {e}")
            return []
    
    def _get_metadata_field(self, summary: Dict[str, Any], field_path: str, default_value=None):
        """Helper method to safely extract fields from metadata_analysis JSON."""
        try:
            metadata_analysis = summary.get('metadata_analysis')
            if not metadata_analysis:
                return default_value if default_value is not None else []
            
            # Navigate nested path (e.g., "universal_metadata.stated_client_problem_summary")
            parts = field_path.split('.')
            current = metadata_analysis
            for part in parts:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return default_value if default_value is not None else []
            
            # Ensure lists are not None
            if isinstance(current, list):
                return current if current is not None else []
            return current if current is not None else (default_value if default_value is not None else [])
            
        except Exception as e:
            self.logger.debug(f"Error extracting metadata field {field_path}: {e}")
            return default_value if default_value is not None else []
    
    def _create_lean_context_for_mission(self, project_context: Dict[str, Any], document_summaries: List[Dict[str, Any]]) -> str:
        """Creates a lean context string for mission and approach synthesis."""
        sow_and_proposal_summaries = [
            s for s in document_summaries
            if s is not None and s.get("source") in ["SoW / Proposal Document", "Project Plan"]
        ]
        
        if not sow_and_proposal_summaries:
            return "No foundational documents available."
        
        context_parts = []
        context_parts.append(f"Project Context: {json.dumps(project_context, indent=2)}")
        
        for summary in sow_and_proposal_summaries:
            # Use new denormalized fields and metadata_analysis for nested data
            doc_context = f"""
Document: {self._safe_get_string(summary, 'document_filename', 'Unknown')} (ID: {self._safe_get_string(summary, 'document_id', 'Unknown')})
Category: {self._safe_get_string(summary, 'document_category', 'Unknown')}
Problem Summary: {self._get_metadata_field(summary, 'project_specific.stated_client_problem_summary', 'N/A')}
Objectives: {self._get_metadata_field(summary, 'project_specific.project_objectives_stated_list', [])}
Timeline: {self._get_metadata_field(summary, 'project_specific.project_phases_timeline_summary', 'N/A')}
Milestones: {self._get_metadata_field(summary, 'project_specific.key_milestones_or_deadlines_list', [])}
Scope: {self._get_metadata_field(summary, 'project_specific.scope_in_list', [])}
Deliverables: {self._get_metadata_field(summary, 'project_specific.key_deliverables_list', [])}
"""
            context_parts.append(doc_context)
        
        return "\n".join(context_parts)
    
    def _create_lean_context_for_readout(self, summaries_for_type: List[Dict[str, Any]]) -> str:
        """Creates a lean context string for strategic intelligence readout."""
        context_parts = []
        for summary in summaries_for_type:
            if summary is None:
                continue
                
            # Use denormalized fields from the new model
            doc_context = f"""
Document: {self._safe_get_string(summary, 'document_filename', 'Unknown')} (ID: {self._safe_get_string(summary, 'document_id', 'Unknown')})
Narrative: {self._safe_get_string(summary, 'narrative_summary', 'N/A')}
Key Takeaways: {self._safe_get_list(summary, 'key_takeaways')}
Objectives: {self._get_metadata_field(summary, 'project_specific.project_objectives_stated_list', [])}
Client Concerns: {self._get_metadata_field(summary, 'project_specific.client_requirements_or_pain_points_expressed_list', [])}
"""
            context_parts.append(doc_context)
        
        return "\n".join(context_parts)
    
    def _synthesize_mission_and_approach(self, project_context: Dict[str, Any], document_summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Synthesizes the 'Mission & Approach' section of the onboarding guide."""
        self.logger.info("Synthesizing 'Mission & Approach' section")
        
        lean_context = self._create_lean_context_for_mission(project_context, document_summaries)
        
        if "No foundational documents available" in lean_context:
            self.logger.info(f"No foundational documents available")
            return {
                "projectMandate": "N/A",
                "keyProjectPhases": [],
                "strategicApproach": [],
            }
        
        # Use loaded prompt with context substitution
        prompt = self.prompts['mission_and_approach'].format(lean_context=lean_context)
        
        try:
            response = self.model.generate_content(prompt)
            # Move logging AFTER response is generated
            self.logger.info(f"Mission & Approach LLM Response: {response.text}")
            
            # Use safe JSON parsing
            result = self._safe_json_parse(response.text)
            
            # Validate the structure and ensure lists are not None
            required_keys = ['projectMandate', 'keyProjectPhases', 'strategicApproach']
            for key in required_keys:
                if key not in result:
                    result[key] = [] if key != 'projectMandate' else "Unable to determine project mandate"
                elif key != 'projectMandate' and result[key] is None:
                    result[key] = []
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error synthesizing 'Mission & Approach' section: {e}")
            # Try fallback model
            try:
                response = self.fallback_model.generate_content(prompt)
                self.logger.info(f"Mission & Approach Fallback LLM Response: {response.text}")
                result = self._safe_json_parse(response.text)
                
                # Validate fallback response
                required_keys = ['projectMandate', 'keyProjectPhases', 'strategicApproach']
                for key in required_keys:
                    if key not in result:
                        result[key] = [] if key != 'projectMandate' else "Unable to determine project mandate"
                    elif key != 'projectMandate' and result[key] is None:
                        result[key] = []
                        
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
        
        # Group summaries by source type, filtering out None values
        summaries_by_source_type = {}
        for summary in document_summaries:
            if summary is None:
                continue
            source_type = summary.get("source", "Unknown")
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
                self.logger.info(f"Strategic Intelligence Readout LLM Response for {source_type}: {response.text}")
                result = self._safe_json_parse(response.text)
                
                # Validate structure and ensure lists are not None
                required_keys = ['comprehensiveSummary', 'keyTakeaways', 'keyThemes']
                for key in required_keys:
                    if key not in result:
                        if key == 'comprehensiveSummary':
                            result[key] = f"Unable to synthesize intelligence for {source_type} documents."
                        else:
                            result[key] = []
                    elif key != 'comprehensiveSummary' and result[key] is None:
                        result[key] = []
                
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
        
        # Create lean document list for prompt with UUID document IDs, filtering None values
        document_context = ""
        for i, s in enumerate(document_summaries):
            if s is None:
                continue
                
            # Use denormalized fields and safe accessors
            key_themes_list = self._safe_get_list(s, "key_themes")
            narrative_summary = self._safe_get_string(s, "narrative_summary")
            
            doc_info = f"""
- Document ID: {self._safe_get_string(s, "document_id", "Unknown")}
- Filename: {self._safe_get_string(s, "document_filename", "Unknown")}
- Source Type: {self._safe_get_string(s, "source", "Unknown")}
- Summary: {narrative_summary[:200] if narrative_summary else "No summary available"}
- Key Themes: {", ".join(key_themes_list[:5]) if key_themes_list else "No themes identified"}
"""
            document_context += doc_info
        
        # Use loaded prompt with context substitution
        prompt = self.prompts['priority_reading_list'].format(document_context=document_context)
        self.logger.info(f"Priority Reading List prompt: {prompt}")
        
        try:
            response = self.model.generate_content(prompt)
            self.logger.info(f"Priority Reading List LLM Response: {response.text}")
            result = self._safe_json_parse(response.text)
            
            # Validate structure
            if "priorityReadingList" not in result:
                raise ValueError("LLM response missing priorityReadingList key")
            
            reading_list = result["priorityReadingList"]
            if not isinstance(reading_list, dict):
                reading_list = {"highPriority": [], "mediumPriority": []}
            
            # Ensure required keys exist and are lists
            for priority_level in ['highPriority', 'mediumPriority']:
                if priority_level not in reading_list or reading_list[priority_level] is None:
                    reading_list[priority_level] = []
            
            # Ensure document IDs in the reading list are UUIDs
            for priority_level in ['highPriority', 'mediumPriority']:
                if priority_level in reading_list and isinstance(reading_list[priority_level], list):
                    for doc in reading_list[priority_level]:
                        if isinstance(doc, dict) and 'documentId' in doc:
                            # Ensure it's a string representation of UUID
                            doc['documentId'] = str(doc['documentId'])
            
            result["priorityReadingList"] = reading_list
            return result
            
        except Exception as e:
            self.logger.error(f"Error identifying 'Priority Reading List': {e}")
            return {"priorityReadingList": {"highPriority": [], "mediumPriority": []}}
    
    def _generate_knowledge_base_faq(self, document_summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generates the 'Knowledge Base FAQ' section of the onboarding guide."""
        self.logger.info("Generating 'Knowledge Base FAQ' section")
        
        # Create curated insights using the denormalized fields from DocumentSummary
        # Filter out None values and use safe list accessors
        valid_summaries = [s for s in document_summaries if s is not None]
        
        curated_insights = {
            "narrativeSummaries": [
                self._safe_get_string(s, "narrative_summary") for s in valid_summaries
                if self._safe_get_string(s, "narrative_summary")
            ][:10],
            "keyThemes": list(set(
                theme for s in valid_summaries
                for theme in self._safe_get_list(s, "key_themes")
            ))[:10],
            "keyTakeaways": [
                takeaway for s in valid_summaries
                for takeaway in self._safe_get_list(s, "key_takeaways")
            ][:15],
            "extractedKeywords": list(set(
                keyword for s in valid_summaries
                for keyword in self._safe_get_list(s, "extracted_keywords")
            ))[:20],
            "documentCategories": list(set(
                self._safe_get_string(s, "document_category") for s in valid_summaries
                if self._safe_get_string(s, "document_category")
            )),
            "documentGroups": list(set(
                self._safe_get_string(s, "document_group") for s in valid_summaries
                if self._safe_get_string(s, "document_group")
            )),
            "suggestedTitles": [
                self._safe_get_string(s, "suggested_title") for s in valid_summaries
                if self._safe_get_string(s, "suggested_title")
            ][:10],
            "impliedAudiences": list(set(
                self._safe_get_string(s, "implied_audience") for s in valid_summaries
                if self._safe_get_string(s, "implied_audience")
            )),
            "geographicalFocus": list(set(
                self._safe_get_string(s, "geographical_focus") for s in valid_summaries
                if self._safe_get_string(s, "geographical_focus")
            )),
            "keyPeople": list(set(
                person for s in valid_summaries
                for person in self._safe_get_list(s, "key_people_mentioned")
            ))[:15],
            "keyOrganizations": list(set(
                org for s in valid_summaries
                for org in self._safe_get_list(s, "key_organizations_mentioned")
            ))[:15],
            "keyDates": list(set(
                date for s in valid_summaries
                for date in self._safe_get_list(s, "key_dates_mentioned")
            ))[:10],
            "documentSentiments": list(set(
                self._safe_get_string(s, "document_sentiment") for s in valid_summaries
                if self._safe_get_string(s, "document_sentiment")
            )),
            "userNotePurposes": [
                self._safe_get_string(s, "user_note_purpose") for s in valid_summaries
                if self._safe_get_string(s, "user_note_purpose")
            ][:10],
            "documentIds": [
                self._safe_get_string(s, "document_id") for s in valid_summaries
                if self._safe_get_string(s, "document_id")
            ]  # Include document UUIDs for reference
        }
        
        # Remove empty lists and None values to clean up the data
        curated_insights = {
            k: v for k, v in curated_insights.items()
            if v and (not isinstance(v, list) or len(v) > 0)
        }
        
        # Use loaded prompt with context substitution
        prompt = self.prompts['knowledge_base_faq'].format(
            curated_insights=json.dumps(curated_insights, indent=2)
        )
        
        try:
            response = self.model.generate_content(prompt)
            self.logger.info(f"Knowledge Base FAQ LLM Response: {response.text}")
            result = json.loads(response.text)
            
            # Validate structure
            if "knowledgeFAQ" not in result:
                raise ValueError("LLM response missing knowledgeFAQ key")
            
            # Ensure knowledgeFAQ is a list
            if not isinstance(result["knowledgeFAQ"], list):
                result["knowledgeFAQ"] = []
            
            # Ensure any document references in FAQ answers use UUID format
            for faq_item in result.get("knowledgeFAQ", []):
                if isinstance(faq_item, dict) and 'relatedDocuments' in faq_item:
                    related_docs = faq_item['relatedDocuments']
                    if isinstance(related_docs, list):
                        faq_item['relatedDocuments'] = [str(doc_id) for doc_id in related_docs if doc_id is not None]
                    elif related_docs is None:
                        faq_item['relatedDocuments'] = []
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error generating 'Knowledge Base FAQ': {e}")
            return {"knowledgeFAQ": []}
    
    def _get_distribution_by_source(self, document_summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Calculates the distribution of documents by source type."""
        if not document_summaries:
            return []
            
        # Filter out None values
        valid_summaries = [s for s in document_summaries if s is not None]
        
        if not valid_summaries:
            return []
            
        source_counts = {}
        for summary in valid_summaries:
            source_type = self._safe_get_string(summary, "source", "Unknown")
            source_counts[source_type] = source_counts.get(source_type, 0) + 1
        
        total_documents = len(valid_summaries)
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
