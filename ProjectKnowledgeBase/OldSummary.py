import json
import os
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass, field
from enum import Enum
import logging
from pathlib import Path
import google.generativeai as genai
import time
from dotenv import load_dotenv
from preprocessing.Processing import MainProcessing

processor=MainProcessing()

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DocumentCategory(Enum):
    STRATEGY_DOCUMENT = "1. Strategy Document/Deck"
    OPERATIONAL_REPORT = "2. Operational Report/Review Deck"
    FINANCIAL_REPORT = "3. Financial Report/Analysis Deck"
    STATEMENT_OF_WORK = "4. Statement of Work (SoW)"
    PROPOSAL_DOCUMENT = "5. Proposal Document"
    FORMAL_CLIENT_DELIVERABLE_REPORT = "6. Formal Client Deliverable (Final Report)"
    FORMAL_CLIENT_DELIVERABLE_PRESENTATION = "7. Formal Client Deliverable (Final Presentation Deck)"
    CLIENT_BRIEF_RFP = "8. Client Brief / Request for Proposal (RFP)"
    MARKET_RESEARCH_REPORT = "9. Market Research Report (Internal/External)"
    MARKET_DATA_DUMP = "10. Market Data Dump/Raw Data File"
    MARKET_SIZING_MODEL = "11. Market Sizing Model/Analysis"
    COMPETITIVE_LANDSCAPE = "12. Competitive Landscape Analysis"
    BENCHMARKING_STUDY = "13. Benchmarking Study/Report"
    SURVEY_INSTRUMENT = "14. Survey Instrument/Questionnaire"
    SURVEY_DATA_ANALYSIS = "15. Survey Data Analysis/Report"
    INDUSTRY_ANALYST_REPORT = "16. Industry Analyst Report"
    ACADEMIC_RESEARCH_PAPER = "17. Academic Research Paper/Journal Article"
    NEWS_ARTICLE = "18. News Article/Web Page Clipping"
    TECHNICAL_SPECIFICATION = "19. Technical Specification Document"
    WORKING_DRAFT_PRESENTATION = "20. Working Draft - Presentation Section"
    WORKING_DRAFT_REPORT = "21. Working Draft - Report Chapter/Section"
    INTERNAL_HYPOTHESES = "22. Internal Working Hypotheses Document"
    PRELIMINARY_ANALYSIS = "23. Preliminary Analysis/Findings Note"
    PROJECT_PLAN = "24. Project Plan Document"
    PROJECT_TIMELINE = "25. Project Timeline/Gantt Chart Visual"
    RISK_REGISTER = "26. Risk Register/Issue Log Document"
    SANITIZED_CASE_STUDY = "27. Sanitized Case Study (from Past Project)"
    LESSONS_LEARNED = "28. Lessons Learned Document (from Past Project)"
    INTERNAL_PROCESS = "29. Internal Process Document/Playbook"
    MEETING_MINUTES_FORMAL = "30. Meeting Minutes (Formal)"
    MEETING_NOTES_INFORMAL = "31. Meeting Notes (Informal)"
    WORKSHOP_AGENDA = "32. Workshop Agenda"
    WORKSHOP_OUTPUT = "33. Workshop Output Summary/Flipchart Notes"
    RAW_TRANSCRIPT = "34. Raw Meeting/Interview Transcript"
    EXPERT_INTERVIEW = "35. Expert Interview Summary/Notes"
    CLIENT_FEEDBACK = "36. Client Feedback (Email/Document)"
    EMAIL_CORRESPONDENCE = "37. Email Correspondence (Key Thread/Summary)"
    STAKEHOLDER_COMMUNICATION = "38. Stakeholder Communication Log"
    GENERIC_TEXT = "39. Generic Text Document"
    USER_SPECIFIED = "40. User Specified (Other)"

class DocumentGroup(Enum):
    GROUP_A = "Strategic & Formal Client-Facing Deliverables/Inputs"
    GROUP_B = "Research, Analysis & Informational Inputs"
    GROUP_C = "Project Execution & Iterative Work Products"
    GROUP_D = "Conversational & Interaction Records"

@dataclass
class DocumentMetadata:
    id: str
    originalFilename: str
    fileSize: int
    fileMimeType: str
    dateAddedToGiani: str
    userID: str
    projectID: str
    textPreview: str
    finalCategory: str
    finalPurpose: str
    priority: str
    finalizedAt: str
    storagePath: str
    categoryFolder: str
    storedFilename: str
    savedAt: str
    # Optional fields that might be present
    tempFilePath: Optional[str] = None
    processedContent: Optional[str] = None
    extractedText: Optional[str] = None
    metadata: Optional[Dict] = field(default_factory=dict)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DocumentMetadata':
        """Create DocumentMetadata from dictionary, handling new format and mapping fields"""
        import dataclasses
        
        # Map new format fields to expected fields
        field_mapping = {
            'document_id': 'id',
            'original_filename': 'originalFilename',
            'file_size': 'fileSize',
            'file_mime_type': 'fileMimeType',
            'date_added': 'dateAddedToGiani',
            'user_id': 'userID',
            'project_id': 'projectID',
            'ai_classification': 'finalCategory',
            'document_purpose': 'finalPurpose',
            'file_path': 'storagePath',
            'document_type': 'categoryFolder',
            'metadata_file_path': 'storedFilename'
        }
        
        # Convert data using field mapping
        converted_data = {}
        for new_key, old_key in field_mapping.items():
            if new_key in data:
                converted_data[old_key] = data[new_key]
        
        # Handle fields that don't have direct mappings
        converted_data.update({
            'textPreview': data.get('textPreview', 'Not available'),
            'finalizedAt': data.get('date_added', 'unknown'),
            'savedAt': data.get('date_added', 'unknown'),
        })
        
        # Get field information from the dataclass
        fields = {f.name: f for f in dataclasses.fields(cls)}
        filtered_data = {}
        
        # Process each field in the dataclass
        for field_name, field_info in fields.items():
            if field_name in converted_data:
                # Use the converted value
                filtered_data[field_name] = converted_data[field_name]
            elif field_info.default != dataclasses.MISSING:
                # Use the field's default value
                filtered_data[field_name] = field_info.default
            elif field_info.default_factory != dataclasses.MISSING:
                # Use the field's default factory
                filtered_data[field_name] = field_info.default_factory()
            else:
                # Provide sensible defaults for required fields that are missing
                if field_info.type == str or field_info.type == 'str':
                    filtered_data[field_name] = 'unknown'
                elif field_info.type == int or field_info.type == 'int':
                    filtered_data[field_name] = 0
                elif field_info.type in [dict, Dict]:
                    filtered_data[field_name] = {}
                else:
                    # For other types, try to provide a reasonable default
                    filtered_data[field_name] = 'unknown'
                
        return cls(**filtered_data)

class DocumentSummarizer:
    def __init__(self, 
                 master_metadata_path: str = 'uploaded_documents/master_metadata.json',
                 gemini_api_key: Optional[str] = None,
                 gemini_model: str = "gemini-1.5-pro"):
        self.master_metadata_path = master_metadata_path
        self.gemini_model = gemini_model
        
        # Initialize Gemini API
        api_key = gemini_api_key or os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError("Gemini API key must be provided either as parameter or GEMINI_API_KEY environment variable")
        
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(gemini_model)
        
        # Configure generation settings for better JSON output
        self.generation_config = genai.types.GenerationConfig(
            temperature=0.1,  # Low temperature for consistent output
            top_p=0.8,
            top_k=40,
            max_output_tokens=8192,
        )
        
        self.category_to_group_mapping = {
            # Strategic & Formal Client-Facing Deliverables/Inputs
            DocumentCategory.STRATEGY_DOCUMENT.value: DocumentGroup.GROUP_A,
            DocumentCategory.OPERATIONAL_REPORT.value: DocumentGroup.GROUP_A,
            DocumentCategory.FINANCIAL_REPORT.value: DocumentGroup.GROUP_A,
            DocumentCategory.STATEMENT_OF_WORK.value: DocumentGroup.GROUP_A,
            DocumentCategory.PROPOSAL_DOCUMENT.value: DocumentGroup.GROUP_A,
            DocumentCategory.FORMAL_CLIENT_DELIVERABLE_REPORT.value: DocumentGroup.GROUP_A,
            DocumentCategory.FORMAL_CLIENT_DELIVERABLE_PRESENTATION.value: DocumentGroup.GROUP_A,
            
            # Research, Analysis & Informational Inputs
            DocumentCategory.MARKET_RESEARCH_REPORT.value: DocumentGroup.GROUP_B,
            DocumentCategory.MARKET_DATA_DUMP.value: DocumentGroup.GROUP_B,
            DocumentCategory.MARKET_SIZING_MODEL.value: DocumentGroup.GROUP_B,
            DocumentCategory.COMPETITIVE_LANDSCAPE.value: DocumentGroup.GROUP_B,
            DocumentCategory.BENCHMARKING_STUDY.value: DocumentGroup.GROUP_B,
            DocumentCategory.SURVEY_INSTRUMENT.value: DocumentGroup.GROUP_B,
            DocumentCategory.SURVEY_DATA_ANALYSIS.value: DocumentGroup.GROUP_B,
            DocumentCategory.INDUSTRY_ANALYST_REPORT.value: DocumentGroup.GROUP_B,
            DocumentCategory.ACADEMIC_RESEARCH_PAPER.value: DocumentGroup.GROUP_B,
            DocumentCategory.NEWS_ARTICLE.value: DocumentGroup.GROUP_B,
            DocumentCategory.TECHNICAL_SPECIFICATION.value: DocumentGroup.GROUP_B,
            DocumentCategory.INTERNAL_HYPOTHESES.value: DocumentGroup.GROUP_B,
            DocumentCategory.PRELIMINARY_ANALYSIS.value: DocumentGroup.GROUP_B,
            
            # Project Execution & Iterative Work Products
            DocumentCategory.WORKING_DRAFT_PRESENTATION.value: DocumentGroup.GROUP_C,
            DocumentCategory.WORKING_DRAFT_REPORT.value: DocumentGroup.GROUP_C,
            DocumentCategory.PROJECT_PLAN.value: DocumentGroup.GROUP_C,
            DocumentCategory.PROJECT_TIMELINE.value: DocumentGroup.GROUP_C,
            DocumentCategory.RISK_REGISTER.value: DocumentGroup.GROUP_C,
            DocumentCategory.SANITIZED_CASE_STUDY.value: DocumentGroup.GROUP_C,
            DocumentCategory.LESSONS_LEARNED.value: DocumentGroup.GROUP_C,
            DocumentCategory.INTERNAL_PROCESS.value: DocumentGroup.GROUP_C,
            
            # Conversational & Interaction Records
            DocumentCategory.CLIENT_BRIEF_RFP.value: DocumentGroup.GROUP_D,
            DocumentCategory.MEETING_MINUTES_FORMAL.value: DocumentGroup.GROUP_D,
            DocumentCategory.MEETING_NOTES_INFORMAL.value: DocumentGroup.GROUP_D,
            DocumentCategory.WORKSHOP_AGENDA.value: DocumentGroup.GROUP_D,
            DocumentCategory.WORKSHOP_OUTPUT.value: DocumentGroup.GROUP_D,
            DocumentCategory.RAW_TRANSCRIPT.value: DocumentGroup.GROUP_D,
            DocumentCategory.EXPERT_INTERVIEW.value: DocumentGroup.GROUP_D,
            DocumentCategory.CLIENT_FEEDBACK.value: DocumentGroup.GROUP_D,
            DocumentCategory.EMAIL_CORRESPONDENCE.value: DocumentGroup.GROUP_D,
            DocumentCategory.STAKEHOLDER_COMMUNICATION.value: DocumentGroup.GROUP_D,
            
            # Default mappings for remaining categories
            DocumentCategory.GENERIC_TEXT.value: DocumentGroup.GROUP_D,
            DocumentCategory.USER_SPECIFIED.value: DocumentGroup.GROUP_D
        }
    
    def load_master_metadata(self) -> Dict[str, Any]:
        """Load the master metadata JSON file with new format"""
        try:
            with open(self.master_metadata_path, 'r', encoding='utf-8') as file:
                data = json.load(file)
                
            # Handle new format - convert to expected format for compatibility
            if 'total_documents' in data:
                # New format detected
                return {
                    "documents": data.get('documents', []),
                    "totalDocuments": data.get('total_documents', 0),
                    "metadata_version": data.get('metadata_version'),
                    "created_date": data.get('created_date'),
                    "last_updated": data.get('last_updated'),
                    "statistics": data.get('statistics', {})
                }
            else:
                # Old format
                return data
                
        except FileNotFoundError:
            logger.error(f"Master metadata file not found: {self.master_metadata_path}")
            return {"documents": [], "totalDocuments": 0}
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing master metadata JSON: {e}")
            return {"documents": [], "totalDocuments": 0}
    
    def get_document_group(self, category: str) -> DocumentGroup:
        """Determine which group a document belongs to based on its category"""
        return self.category_to_group_mapping.get(category, DocumentGroup.GROUP_D)
    
    def extract_document_chunks(self, document_path: str) -> str:
        """Extract key document content chunks from the document file"""
        try:
            # Ensure the path is absolute or relative to the correct base directory
            if not os.path.isabs(document_path):
                # If it's a relative path, assume it's relative to the working directory
                full_path = os.path.join(os.getcwd(), document_path)
            else:
                full_path = document_path
                
            if not os.path.exists(full_path):
                logger.warning(f"Document file not found: {full_path}")
                return f"Document file not found: {full_path}"
                
            content = processor.process_files(str(full_path))
            return content
            
        except Exception as e:
            logger.error(f"Error extracting content from {document_path}: {e}")
            return f"Error reading document: {str(e)}"

    def call_llm_api(self, prompt: str, max_retries: int = 3, retry_delay: float = 1.0) -> Optional[Dict[str, Any]]:
        """
        Call Gemini API with the generated prompt and return parsed JSON response
        """
        for attempt in range(max_retries):
            try:
                logger.info(f"Calling Gemini API (attempt {attempt + 1}/{max_retries})")
                
                # Make the API call to Gemini
                response = self.model.generate_content(
                    prompt,
                    generation_config=self.generation_config
                )
                
                # Check if the response was blocked or had issues
                if not response.text:
                    logger.error("Gemini API returned empty response")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                    return None
                
                # Try to parse the JSON response
                try:
                    # Clean the response text - sometimes Gemini wraps JSON in markdown
                    response_text = response.text.strip()
                    if response_text.startswith('```json'):
                        response_text = response_text[7:]  # Remove ```json
                    if response_text.endswith('```'):
                        response_text = response_text[:-3]  # Remove ```
                    
                    response_text = response_text.strip()
                    
                    # Parse JSON
                    llm_response = json.loads(response_text)
                    
                    # Add model information to response
                    llm_response["llm_used_for_processing"] = f"gemini-{self.gemini_model}"
                    
                    logger.info("Successfully received and parsed Gemini API response")
                    return llm_response
                    
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON response from Gemini: {e}")
                    logger.error(f"Raw response: {response.text[:500]}...")
                    
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                    return None
                    
            except Exception as e:
                logger.error(f"Error calling Gemini API: {e}")
                
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (2 ** attempt))  # Exponential backoff
                    continue
                    
                return None
        
        logger.error(f"Failed to get valid response from Gemini API after {max_retries} attempts")
        return None

    def get_group_a_prompt(self, originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
        """Generate Group A prompt for Strategic & Formal Client-Facing Deliverables/Inputs"""
        return f"""ROLE:
You are an AI Knowledge Analyst for Giani.ai, specializing in extracting and structuring critical information from consulting project documents for use by management consultants. Your output must be factual, concise, and directly derived from the provided text.

INPUT DOCUMENT DETAILS:
- Filename: '{originalFilename}'
- User-Defined Document Source Type: '{documentSourceType}'
- User Note on Document Purpose for this Project: '''{userNoteOnPurpose}'''
- Extracted Key Document Content/Chunks: '''{key_document_chunks}'''

YOUR TASK:
Based ONLY on the provided 'Extracted Key Document Content/Chunks' and heavily guided by the 'User Note on Document Purpose' and the 'User-Defined Document Source Type':

1.  **Comprehensive Document Distillation:**
    *   **Identify and list 3-5 OVERALL KEY THEMES** covered in this document. These should be concise phrases reflecting the main subject areas or strategic pillars.
    *   Generate a **CONCISE HIGH-LEVEL NARRATIVE SUMMARY** (typically 1-2 paragraphs for reports/formal documents) that captures the absolute essence of this document *as it relates to its stated purpose for this project*.
    *   Identify **3-5 MAIN TOPICS** discussed or presented within the document. These should be clear, distinct subject headings.
    *   For each identified MAIN TOPIC, provide a **1-2 sentence summary** capturing the core information or key message related to that specific topic within the document.
    *   Extract/formulate **3-5 specific KEY TAKEAWAYS** as bullet points that a consultant would find most valuable for quick understanding, decision-making, or action (these might overlap with topic summaries but should be distinctly actionable or critical insights).

2.  **Specific Metadata Field Extraction:**
    *   Extract the following specific metadata attributes relevant to a '{documentSourceType}'.
    *   If a field's information is not clearly present or inferable from the provided content, output "Not Found" or null for that field.
    *   Extract the following strategic and formal reporting elements:
        -   `project_objectives_stated_list`: Clearly stated primary goals or objectives of the project/document.
        -   `key_recommendations_or_proposals_list`: Main recommendations, solutions, or proposals put forth.
        -   `key_performance_indicators_metrics_list_of_objects`: Specific metrics or KPIs discussed, including their values and periods if mentioned (e.g., {{"metric": "Revenue Growth", "value": "15%", "period": "YoY"}}).
        -   `primary_conclusions_list`: The main conclusions drawn or results presented.
        -   `target_audience_explicit`: If the document explicitly states its target audience.
        -   `executive_summary_points_list`: If an explicit executive summary exists, list its main bullet points or themes.
    *   If '{documentSourceType}' is "SoW / Proposal Document", also extract:
        -   `sow_proposal_details.scope_in_list`: Primary In-Scope activities/areas.
        -   `sow_proposal_details.scope_out_list`: Explicitly Out-of-Scope items.
        -   `sow_proposal_details.key_deliverables_list`: List of Key Deliverables.
        -   `sow_proposal_details.project_phases_timeline_summary`: High-level Project Phases or Timeline highlights.
        -   `sow_proposal_details.client_stakeholders_list`: Named Client Stakeholders or the main client organization.
        -   `sow_proposal_details.stated_client_problem_summary`: The core client problem the SoW/Proposal addresses.
    *   If '{documentSourceType}' is "Client Financial Data/Report", also extract:
        -   `financial_report_details.reporting_period`: The primary Reporting Period covered.
        -   `financial_report_details.currency`: Main Currency used.
        -   `financial_report_details.financial_trends_summary`: Significant Financial Trends or Anomalies highlighted.
        -   `financial_report_details.report_conclusions`: Any stated Conclusions drawn from the financial data.

3.  **Universal Metadata Field Extraction (Attempt for most document types):**
    *   `suggested_document_title`: (A concise, descriptive title if `originalFilename` is not ideal).
    *   `implied_audience`: (e.g., "Executive Leadership," "Technical Team," "Client Working Group," "Internal Team Only").
    *   `key_dates_mentioned`: (List any specific dates or date ranges like "Q3 2024", "FY2025")
    *   `key_people_or_roles_mentioned`: (List prominent individuals or roles).
    *   `key_companies_organizations_mentioned`: (List prominent organizations).
    *   `primary_geographical_focus`: (If discernible, e.g., "North America," "APAC," "Global").
    *   `document_overall_sentiment`: (e.g., "Positive", "Negative", "Neutral", "Mixed", "Objective").
    *   `key_questions_answered_or_posed`: (List key questions the document aims to answer or raises).
    *   `main_methodology_or_approach_used`: (e.g., "Strategic Framework Application", "Financial Analysis", "Not Applicable").

4.  **Keyword Generation:**
    *   Identify and list 5-7 GENERAL KEYWORDS from the document that best represent its core content, focusing on strategic terms.

OUTPUT FORMAT (Strictly JSON):
{{
  "ai_overall_key_themes_list": ["...", "...", "..."],
  "ai_high_level_narrative_summary": "...",
  "ai_main_topics_with_summaries_list_of_objects": [
    {{"topic_name": "...", "topic_summary": "..."}},
    {{"topic_name": "...", "topic_summary": "..."}}
  ],
  "ai_key_takeaways_bullets": ["...", "...", "..."],
  "extracted_metadata": {{
    "suggested_document_title": "...",
    "implied_audience": "...",
    "key_dates_mentioned": ["...", "..."],
    "key_people_or_roles_mentioned": ["...", "..."],
    "key_companies_organizations_mentioned": ["...", "..."],
    "primary_geographical_focus": "...",
    "document_overall_sentiment": "...",
    "key_questions_answered_or_posed": ["...", "..."],
    "main_methodology_or_approach_used": "...",
    "cluster_a_specific_metadata": {{
      "project_objectives_stated_list": ["..."],
      "key_recommendations_or_proposals_list": ["..."],
      "key_performance_indicators_metrics_list_of_objects": [{{"metric": "...", "value": "...", "period": "..."}}],
      "primary_conclusions_list": ["..."],
      "target_audience_explicit": "...",
      "executive_summary_points_list": ["..."],
      "sow_proposal_details": {{
        "scope_in_list": ["..."],
        "scope_out_list": ["..."],
        "key_deliverables_list": ["..."],
        "project_phases_timeline_summary": "...",
        "client_stakeholders_list": ["..."],
        "stated_client_problem_summary": "..."
      }},
      "financial_report_details": {{
        "reporting_period": "...",
        "currency": "...",
        "financial_trends_summary": "...",
        "report_conclusions": "..."
      }}
    }}
  }},
  "extracted_keywords": ["...", "..."],
  "llm_used_for_processing": "model_name_version_used_for_this_summary"
}}"""

    def get_group_b_prompt(self, originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
        """Generate Group B prompt for Research, Analysis & Informational Inputs"""
        return f"""ROLE:
You are an AI Knowledge Analyst for Giani.ai, specializing in extracting and structuring critical information from consulting project documents for use by management consultants. Your output must be factual, concise, and directly derived from the provided text.

INPUT DOCUMENT DETAILS:
- Filename: '{originalFilename}'
- User-Defined Document Source Type: '{documentSourceType}'
- User Note on Document Purpose for this Project: '''{userNoteOnPurpose}'''
- Extracted Key Document Content/Chunks: '''{key_document_chunks}'''

YOUR TASK:
Based ONLY on the provided 'Extracted Key Document Content/Chunks' and heavily guided by the 'User Note on Document Purpose' and the 'User-Defined Document Source Type':

1.  **Comprehensive Document Distillation:**
    *   **Identify and list 3-5 OVERALL KEY THEMES** covered in this research/analysis document. These should be concise phrases reflecting the main areas of investigation or findings.
    *   Generate a **CONCISE HIGH-LEVEL NARRATIVE SUMMARY** (typically 1-2 paragraphs, focusing on key data, methodologies, and analytical findings) that captures the absolute essence of this document *as it relates to its stated purpose for this project*.
    *   Identify **3-5 MAIN TOPICS** (e.g., specific analyses, data categories, research sections) discussed or presented within the document. These should be clear, distinct subject headings.
    *   For each identified MAIN TOPIC, provide a **1-2 sentence summary** capturing the core information, key data, or analytical conclusion related to that specific topic within the document.
    *   Extract/formulate **3-5 specific KEY TAKEAWAYS** as bullet points that a consultant would find most valuable for quick understanding of the research outcomes or critical data points.

2.  **Specific Metadata Field Extraction:**
    *   Extract the following specific metadata attributes relevant to a '{documentSourceType}'.
    *   If a field's information is not clearly present or inferable from the provided content, output "Not Found" or null for that field.
    *   Extract the following research and analysis elements:
        -   `primary_research_questions_hypotheses_list`: The main questions the research/analysis aimed to answer or hypotheses tested.
        -   `key_data_sources_used_list`: List of primary data sources mentioned or evident (e.g., "Internal sales data", "Industry Report by Gartner").
        -   `core_analytical_findings_insights_list`: The most significant findings or insights derived from the analysis.
        -   `methodologies_analytical_techniques_list`: Key methodologies or analytical techniques employed (e.g., "Regression Analysis", "Qualitative Survey").
        -   `stated_limitations_of_analysis_list`: Any explicitly mentioned limitations of the research or analysis.
        -   `key_data_tables_figures_description_list`: Brief descriptions of any crucial tables or figures presented (e.g., title or caption of the table/figure).

3.  **Universal Metadata Field Extraction (Attempt for most document types):**
    *   `suggested_document_title`: (A concise, descriptive title if `originalFilename` is not ideal).
    *   `implied_audience`: (e.g., "Internal Research Team," "Project Lead," "Strategy Department").
    *   `key_dates_mentioned`: (List any specific dates or date ranges like "Q3 2024", "FY2025", "Survey conducted in May 2023")
    *   `key_people_or_roles_mentioned`: (List prominent individuals, roles, or authoring institutions).
    *   `key_companies_organizations_mentioned`: (List prominent organizations discussed or sourced from).
    *   `primary_geographical_focus`: (If discernible, e.g., "Global Market," "North America," "Specific City").
    *   `document_overall_sentiment`: (Typically "Objective" or "Neutral" for research, but can vary).
    *   `key_questions_answered_or_posed`: (List key questions the document aims to answer or raises).
    *   `main_methodology_or_approach_used`: (List the primary research/analysis methodology if not captured above).

4.  **Keyword Generation:**
    *   Identify and list 5-7 GENERAL KEYWORDS from the document that best represent its core content, focusing on analytical and research terms.

OUTPUT FORMAT (Strictly JSON):
{{
  "ai_overall_key_themes_list": ["Theme 1", "Theme 2", "Theme 3"],
  "ai_high_level_narrative_summary": "This document analyzes market trends for X...",
  "ai_main_topics_with_summaries_list_of_objects": [
    {{
      "topic_name": "Market Sizing Analysis",
      "topic_summary": "The total addressable market is estimated at $Y billion. Key growth drivers include Z."
    }},
    {{
      "topic_name": "Competitive Landscape",
      "topic_summary": "Company A holds the largest market share. New entrants are focusing on niche B."
    }}
  ],
  "ai_key_takeaways_bullets": [
    "Key finding 1 related to market growth.",
    "Important insight about competitor strategy.",
    "Data point X shows significant trend Y."
  ],
  "extracted_metadata": {{
    "suggested_document_title": "Comprehensive Market Analysis for Product X - 2024",
    "implied_audience": "Strategy Team",
    "key_dates_mentioned": ["2023 Data", "Projections for 2025-2027"],
    "key_people_or_roles_mentioned": ["Dr. Analyst (Author)", "Research Division"],
    "key_companies_organizations_mentioned": ["Competitor A", "Competitor B", "Sourced from Industry Analysts Inc."],
    "primary_geographical_focus": "North America",
    "document_overall_sentiment": "Objective",
    "key_questions_answered_or_posed": ["What is the current market size?", "Who are the key competitors?"],
    "main_methodology_or_approach_used": "Secondary Research Analysis",
    "cluster_b_specific_metadata": {{
      "primary_research_questions_hypotheses_list": ["Determine market viability for new product line."],
      "key_data_sources_used_list": ["Gartner Report Q1 2024", "Statista", "Internal Sales Data FY2023"],
      "core_analytical_findings_insights_list": ["Segment X is underserved.", "High barrier to entry for new players."],
      "methodologies_analytical_techniques_list": ["SWOT Analysis", "Market Segmentation"],
      "stated_limitations_of_analysis_list": ["Data for APAC region was limited.", "Projections based on current economic climate."],
      "key_data_tables_figures_description_list": ["Table 1: Market Share Breakdown", "Figure 2: Growth Projections"]
    }}
  }},
  "extracted_keywords": ["Market Analysis", "Competitive Landscape", "Market Sizing", "Growth Drivers", "Industry Trends"],
  "llm_used_for_processing": "model_name_version_used_for_this_summary"
}}"""

    def get_group_c_prompt(self, originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
        """Generate Group C prompt for Project Execution & Iterative Work Products"""
        return f"""ROLE:
You are an AI Knowledge Analyst for Giani.ai, specializing in extracting and structuring critical information from consulting project documents for use by management consultants. Your output must be factual, concise, and directly derived from the provided text.

INPUT DOCUMENT DETAILS:
- Filename: '{originalFilename}'
- User-Defined Document Source Type: '{documentSourceType}'
- User Note on Document Purpose for this Project: '''{userNoteOnPurpose}'''
- Extracted Key Document Content/Chunks: '''{key_document_chunks}'''

YOUR TASK:
Based ONLY on the provided 'Extracted Key Document Content/Chunks' and heavily guided by the 'User Note on Document Purpose' and the 'User-Defined Document Source Type':

1.  **Comprehensive Document Distillation:**
    *   **Identify and list 3-5 OVERALL KEY THEMES** covered in this project execution/work product document. These should be concise phrases reflecting the main areas of content, status, or project phases.
    *   Generate a **CONCISE HIGH-LEVEL NARRATIVE SUMMARY** (typically 3-5 bullet points or a short paragraph, focusing on status, key content areas, main risks, or primary lessons) that captures the absolute essence of this document *as it relates to its stated purpose for this project*.
    *   Identify **3-5 MAIN TOPICS** (e.g., key sections of a draft, major project phases, risk categories, core lessons) discussed or presented within the document. These should be clear, distinct subject headings.
    *   For each identified MAIN TOPIC, provide a **1-2 sentence summary** capturing the core information, status, or key message related to that specific topic within the document.
    *   Extract/formulate **3-5 specific KEY TAKEAWAYS** as bullet points that a consultant would find most valuable for quick understanding of project progress, critical issues, or actionable learnings.

2.  **Specific Metadata Field Extraction:**
    *   Extract the following specific metadata attributes relevant to a '{documentSourceType}'.
    *   If a field's information is not clearly present or inferable from the provided content, output "Not Found" or null for that field.
    *   Extract the following project execution and iterative work elements:
        -   `main_sections_or_topics_covered_list`: Key sections, chapters, or topics addressed in the document.
        -   `document_status_or_version`: (e.g., "Draft V1.2", "Final for Review", "Approved Plan", "Lessons Learned V1").
        -   `key_risks_issues_status_list_of_objects`: For risk registers or project plans, list key risks/issues with their status or mitigation if mentioned (e.g., {{"risk": "Vendor Delay", "status": "Mitigated", "mitigation": "Alternate supplier identified"}}).
        -   `key_milestones_or_deadlines_list`: Important milestones or deadlines from plans/timelines.
        -   `lessons_learned_summary_points_list`: For case studies/lessons learned, key takeaways or lessons.
        -   `next_steps_or_pending_actions_list`: For working drafts or plans, any implied or stated next steps or pending actions.

3.  **Universal Metadata Field Extraction (Attempt for most document types):**
    *   `suggested_document_title`: (A concise, descriptive title if `originalFilename` is not ideal).
    *   `implied_audience`: (e.g., "Project Team," "Steering Committee," "Internal Knowledge Management").
    *   `key_dates_mentioned`: (List any specific dates or date ranges for milestones, phases, review dates)
    *   `key_people_or_roles_mentioned`: (List key project team members, stakeholders, or authors).
    *   `key_companies_organizations_mentioned`: (List relevant client or internal organizations).
    *   `primary_geographical_focus`: (If applicable, e.g., "Project scope: EMEA").
    *   `document_overall_sentiment`: (e.g., "Constructive", "Cautionary", "Informative", "Neutral").
    *   `key_questions_answered_or_posed`: (List key questions the document addresses, e.g., "What are the key project risks?").
    *   `main_methodology_or_approach_used`: (e.g., "Agile Project Management", "Risk Assessment Framework", "Not Applicable").

4.  **Keyword Generation:**
    *   Identify and list 5-7 GENERAL KEYWORDS from the document that best represent its core content, focusing on project management, process, or deliverable terms.

OUTPUT FORMAT (Strictly JSON):
{{
  "ai_overall_key_themes_list": ["Project Planning", "Risk Management", "Stakeholder Alignment"],
  "ai_high_level_narrative_summary": "This document outlines the project plan for Phase 2, highlighting key milestones, resource allocation, and identified risks.",
  "ai_main_topics_with_summaries_list_of_objects": [
    {{
      "topic_name": "Phase 2 Timeline",
      "topic_summary": "Phase 2 is scheduled to run from 2024-08-01 to 2024-10-31. Key deliverables include X and Y."
    }},
    {{
      "topic_name": "Risk Register Overview",
      "topic_summary": "Three high-priority risks have been identified, with mitigation plans in place for two."
    }}
  ],
  "ai_key_takeaways_bullets": [
    "Critical deadline for deliverable Y is 2024-09-15.",
    "Risk Z requires immediate attention from the Steering Committee.",
    "Lesson learned from previous phase: Improve communication frequency."
  ],
  "extracted_metadata": {{
    "suggested_document_title": "Project Phoenix - Phase 2 Detailed Plan & Risk Assessment",
    "implied_audience": "Project Steering Committee",
    "key_dates_mentioned": ["2024-08-01 (Phase Start)", "2024-10-31 (Phase End)", "Weekly review meetings"],
    "key_people_or_roles_mentioned": ["John Smith (Project Manager)", "Client Sponsor Name"],
    "key_companies_organizations_mentioned": ["ClientOrg LLC", "Vendor Partner Corp"],
    "primary_geographical_focus": "Global (Remote Team)",
    "document_overall_sentiment": "Proactive & Planned",
    "key_questions_answered_or_posed": ["What is the timeline for Phase 2?", "What are the major risks?"],
    "main_methodology_or_approach_used": "Waterfall with Agile Sprints for Development",
    "cluster_c_specific_metadata": {{
      "main_sections_or_topics_covered_list": ["Introduction", "Phase 2 Workstreams", "Resource Plan", "Risk Register", "Communication Plan"],
      "document_status_or_version": "Approved V1.0",
      "key_risks_issues_status_list_of_objects": [
        {{"risk": "Resource Unavailability", "status": "Medium", "mitigation": "Cross-training in progress"}},
        {{"risk": "Scope Creep", "status": "Low", "mitigation": "Strict change control process"}}
      ],
      "key_milestones_or_deadlines_list": ["Design Freeze: 2024-08-30", "UAT Start: 2024-10-01"],
      "lessons_learned_summary_points_list": ["Ensure dedicated SME time for requirements gathering."],
      "next_steps_or_pending_actions_list": ["Schedule Phase 2 Kick-off meeting.", "Finalize resource allocation with department heads."]
    }}
  }},
  "extracted_keywords": ["Project Plan", "Risk Management", "Timeline", "Milestones", "Deliverables", "Status Report"],
  "llm_used_for_processing": "model_name_version_used_for_this_summary"
}}"""

    def get_group_d_prompt(self, originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
        """Generate Group D prompt for Conversational & Interaction Records"""
        return f"""ROLE:
You are an AI Knowledge Analyst for Giani.ai, specializing in extracting and structuring critical information from consulting project documents for use by management consultants. Your output must be factual, concise, and directly derived from the provided text.

INPUT DOCUMENT DETAILS:
- Filename: '{originalFilename}'
- User-Defined Document Source Type: '{documentSourceType}'
- User Note on Document Purpose for this Project: '''{userNoteOnPurpose}'''
- Extracted Key Document Content/Chunks: '''{key_document_chunks}'''

YOUR TASK:
Based ONLY on the provided 'Extracted Key Document Content/Chunks' and heavily guided by the 'User Note on Document Purpose' and the 'User-Defined Document Source Type':

1.  **Comprehensive Document Distillation:**
    *   **Identify and list 3-5 OVERALL KEY THEMES** covered in this interaction record. These should be concise phrases reflecting the main subjects of discussion, feedback categories, or client needs.
    *   Generate a **CONCISE HIGH-LEVEL NARRATIVE SUMMARY** (typically in bullet point format, focusing on key decisions, action items, or expressed needs/sentiments) that captures the absolute essence of this interaction *as it relates to its stated purpose for this project*.
    *   Identify **3-5 MAIN TOPICS** (e.g., specific agenda items, key questions asked, feedback areas, expressed client requirements) discussed or presented within the document. These should be clear, distinct subject headings.
    *   For each identified MAIN TOPIC, provide a **1-2 sentence summary** capturing the core information, decision, action, or sentiment related to that specific topic within the document.
    *   Extract/formulate **3-5 specific KEY TAKEAWAYS** as bullet points that a consultant would find most valuable for quick understanding of outcomes, required follow-ups, or critical client input.

2.  **Specific Metadata Field Extraction:**
    *   Extract the following specific metadata attributes relevant to a '{documentSourceType}'.
    *   If a field's information is not clearly present or inferable from the provided content, output "Not Found" or null for that field.
    *   Extract from these notes/transcript/email/brief:
        -   `interaction_date`: Date of meeting/interaction/document creation.
        -   `key_attendees_or_participants_list`: Key individuals or groups involved/addressed/cc'd.
        -   `main_topics_or_agenda_items_discussed_list`: Main subjects of discussion, agenda points, or purpose of the communication.
        -   `key_decisions_made_list_of_objects`: Distinct decisions made, who made them (if clear), and rationale (if clear) (e.g., {{"decision": "Proceed with Option A", "decision_maker": "Steering Committee", "rationale": "Lowest risk profile"}}).
        -   `distinct_action_items_list_of_objects`: Specific action items with assigned owners and deadlines if specified (e.g., {{"action": "Schedule follow-up", "owner": "John Doe", "deadline": "2024-07-15"}}).
        -   `unresolved_issues_or_parking_lot_items_list`: Any open questions, issues to be addressed later, or points deferred.
        -   `client_requirements_or_pain_points_expressed_list`: For briefs/RFPs or client feedback/emails, specific needs, requirements, or problems highlighted by the client/sender.

3.  **Universal Metadata Field Extraction (Attempt for most document types):**
    *   `suggested_document_title`: (A concise, descriptive title, e.g., "Meeting Summary - Q3 Strategy" or "Client Feedback - Project Alpha").
    *   `implied_audience`: (e.g., "Project Team," "Client Contact," "Internal Record").
    *   `key_dates_mentioned`: (List any specific dates mentioned for follow-ups, deadlines, or events)
    *   `key_people_or_roles_mentioned`: (List key individuals or roles discussed or involved beyond attendees).
    *   `key_companies_organizations_mentioned`: (List prominent organizations discussed).
    *   `primary_geographical_focus`: (If relevant to the discussion, e.g., "Discussion focused on APAC market").
    *   `document_overall_sentiment`: (e.g., "Positive Client Feedback", "Urgent Action Required", "Neutral Update", "Concern Raised").
    *   `key_questions_answered_or_posed`: (List key questions that were central to the interaction).
    *   `main_methodology_or_approach_used`: (Typically "Not Applicable" for this cluster, unless it's a structured interview or workshop output).

4.  **Keyword Generation:**
    *   Identify and list 5-7 GENERAL KEYWORDS from the document that best represent its core content, focusing on interaction, decision, and feedback terms.

OUTPUT FORMAT (Strictly JSON):
{{
  "ai_overall_key_themes_list": ["Client Concerns", "Project Timeline Adjustments", "Next Steps"],
  "ai_high_level_narrative_summary": [
    "Client expressed concerns regarding X.",
    "Agreed to adjust timeline for Y.",
    "Key action items assigned to Z."
  ],
  "ai_main_topics_with_summaries_list_of_objects": [
    {{
      "topic_name": "Budget Constraints Discussion",
      "topic_summary": "Client highlighted budget constraints for Q4. Explored potential cost-saving measures."
    }},
    {{
      "topic_name": "Action Item Review",
      "topic_summary": "Reviewed outstanding action items from previous meeting. A.I. #3 marked as complete."
    }}
  ],
  "ai_key_takeaways_bullets": [
    "Urgent: Follow up with client on budget options by EOW.",
    "Decision: Project X will be prioritized over Project Y.",
    "Feedback: Client is generally positive but has specific concerns about Z."
  ],
  "extracted_metadata": {{
    "suggested_document_title": "Weekly Client Check-in - Project Alpha - 2024-07-22",
    "implied_audience": "Project Team, Account Manager",
    "key_dates_mentioned": ["2024-07-22 (Meeting Date)", "Next meeting: 2024-07-29", "Deliverable due: 2024-08-15"],
    "key_people_or_roles_mentioned": ["Sarah (Client Lead)", "Mark (Technical Lead)"],
    "key_companies_organizations_mentioned": ["Client Corp"],
    "primary_geographical_focus": "Not Applicable",
    "document_overall_sentiment": "Mixed (Positive with specific concerns)",
    "key_questions_answered_or_posed": ["What is the status of deliverable X?", "Are there any budget concerns?"],
    "main_methodology_or_approach_used": "Not Applicable",
    "cluster_d_specific_metadata": {{
      "interaction_date": "2024-07-22",
      "key_attendees_or_participants_list": ["Sarah (Client)", "Tom (Consultant Lead)", "Lisa (Consultant)"],
      "main_topics_or_agenda_items_discussed_list": ["Review of last week's progress", "Q4 Budget Discussion", "Next Steps Planning"],
      "key_decisions_made_list_of_objects": [
        {{"decision": "Defer Feature X to Phase 2", "decision_maker": "Sarah (Client)", "rationale": "Budget constraints"}},
        {{"decision": "Hold bi-weekly technical reviews", "decision_maker": "Tom (Consultant Lead)", "rationale": "Improve alignment"}}
      ],
      "distinct_action_items_list_of_objects": [
        {{"action": "Lisa to send revised budget proposal", "owner": "Lisa (Consultant)", "deadline": "2024-07-24"}},
        {{"action": "Sarah to confirm stakeholder availability for demo", "owner": "Sarah (Client)", "deadline": "2024-07-26"}}
      ],
      "unresolved_issues_or_parking_lot_items_list": ["Long-term impact of deferring Feature X.", "Requirement for additional specialized resources."],
      "client_requirements_or_pain_points_expressed_list": ["Need clear visibility on budget spend.", "Concerned about integration timeline with legacy systems."]
    }}
  }},
  "extracted_keywords": ["Meeting Minutes", "Client Feedback", "Action Items", "Decisions Made", "Project Update"],
  "llm_used_for_processing": "model_name_version_used_for_this_summary"
}}"""
    
    def get_appropriate_prompt(self, document: DocumentMetadata, key_document_chunks: str) -> str:
        """Get the appropriate prompt based on document category"""
        group = self.get_document_group(document.finalCategory)
        
        if group == DocumentGroup.GROUP_A:
            return self.get_group_a_prompt(
                document.originalFilename,
                document.finalCategory,
                document.finalPurpose,
                key_document_chunks
            )
        elif group == DocumentGroup.GROUP_B:
            return self.get_group_b_prompt(
                document.originalFilename,
                document.finalCategory,
                document.finalPurpose,
                key_document_chunks
            )
        elif group == DocumentGroup.GROUP_C:
            return self.get_group_c_prompt(
                document.originalFilename,
                document.finalCategory,
                document.finalPurpose,
                key_document_chunks
            )
        else:  # GROUP_D
            return self.get_group_d_prompt(
                document.originalFilename,
                document.finalCategory,
                document.finalPurpose,
                key_document_chunks
            )

    def summarize_document(self, document: DocumentMetadata) -> Optional[Dict[str, Any]]:
        """Summarize a single document based on its category"""
        try:
            # Extract document content
            key_document_chunks = self.extract_document_chunks(document.storagePath)
            
            # Get appropriate prompt
            prompt = self.get_appropriate_prompt(document, key_document_chunks)
            
            # Call Gemini API
            llm_response = self.call_llm_api(prompt)
            
            if llm_response:
                # Add document metadata to response
                result = {
                    "document_id": document.id,
                    "document_filename": document.originalFilename,
                    "document_category": document.finalCategory,
                    "document_group": self.get_document_group(document.finalCategory).value,
                    "user_note_purpose": document.finalPurpose,
                    "processing_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                    "llm_analysis": llm_response
                }
                
                logger.info(f"Successfully processed document: {document.originalFilename}")
                return result
            else:
                logger.error(f"Gemini API call failed for document: {document.originalFilename}")
                return None
                
        except Exception as e:
            logger.error(f"Error summarizing document {document.id}: {e}")
            return None

    def process_all_documents(self) -> List[Dict[str, Any]]:
        """Process all documents in the master metadata file"""
        metadata = self.load_master_metadata()
        results = []
        
        logger.info(f"Processing {metadata.get('totalDocuments', 0)} documents")
        
        for doc_data in metadata.get('documents', []):
            try:
                # Convert dict to DocumentMetadata object using the safe method
                document = DocumentMetadata.from_dict(doc_data)
                
                # Summarize the document
                result = self.summarize_document(document)
                
                if result:
                    results.append(result)
                else:
                    logger.warning(f"Failed to process document: {document.originalFilename}")
                    
            except Exception as e:
                logger.error(f"Error processing document {doc_data.get('document_id', doc_data.get('id', 'unknown'))}: {e}")
                
        return results

    def save_results(self, results: List[Dict[str, Any]], output_path: str = "summarization_results.json"):
        """Save summarization results to a JSON file"""
        try:
            output_data = {
                "summarization_results": results,
                "total_processed": len(results),
                "processing_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                "version": "1.0"
            }
            
            with open(output_path, 'w', encoding='utf-8') as file:
                json.dump(output_data, file, indent=2, ensure_ascii=False)
                
            logger.info(f"Results saved to {output_path}")
            
        except Exception as e:
            logger.error(f"Error saving results: {e}")

def main():
    """Main execution function"""
    # Initialize the summarizer with Gemini API
    # You can pass the API key directly or set GEMINI_API_KEY environment variable
    summarizer = DocumentSummarizer(
        gemini_api_key=None,  # Will use GEMINI_API_KEY env var
        gemini_model="gemini-1.5-pro"  # or "gemini-1.5-flash" for faster/cheaper processing
    )
    
    # Process all documents
    results = summarizer.process_all_documents()
    
    # Save results
    summarizer.save_results(results)
    
    # Print summary
    print(f"\n=== Summarization Complete ===")
    print(f"Total documents processed: {len(results)}")
    print(f"Results saved to: summarization_results.json")
    
    # Group results by category
    category_counts = {}
    for result in results:
        category = result.get('document_category', 'Unknown')
        category_counts[category] = category_counts.get(category, 0) + 1
    
    print(f"\nDocuments by category:")
    for category, count in category_counts.items():
        print(f"  - {category}: {count}")

if __name__ == "__main__":
    main()
