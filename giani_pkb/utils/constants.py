from enum import Enum

DOCUMENT_TYPES = [
    "Client-Provided Material",
    "Internal Research & Analysis",
    "Current Project Working Draft",
    "Past Similar Project Reference",
    "Meeting Notes/Transcripts",
    "SoW / Proposal Document",
    "External Third-Party Report",
    "Other"
]

AI_CLASSIFICATIONS = [
    "1. Strategy Document/Deck",
    "2. Operational Report/Review Deck",
    "3. Financial Report/Analysis Deck",
    "4. Statement of Work (SoW)",
    "5. Proposal Document",
    "6. Formal Client Deliverable (Final Report)",
    "7. Formal Client Deliverable (Final Presentation Deck)",
    "8. Client Brief / Request for Proposal (RFP)",
    "9. Market Research Report (Internal/External)",
    "10. Market Data Dump/Raw Data File",
    "11. Market Sizing Model/Analysis",
    "12. Competitive Landscape Analysis",
    "13. Benchmarking Study/Report",
    "14. Survey Instrument/Questionnaire",
    "15. Survey Data Analysis/Report",
    "16. Industry Analyst Report",
    "17. Academic Research Paper/Journal Article",
    "18. News Article/Web Page Clipping",
    "19. Technical Specification Document",
    "20. Working Draft - Presentation Section",
    "21. Working Draft - Report Chapter/Section",
    "22. Internal Working Hypotheses Document",
    "23. Preliminary Analysis/Findings Note",
    "24. Project Plan Document",
    "25. Project Timeline/Gantt Chart Visual",
    "26. Risk Register/Issue Log Document",
    "27. Sanitized Case Study (from Past Project)",
    "28. Lessons Learned Document (from Past Project)",
    "29. Internal Process Document/Playbook",
    "30. Meeting Minutes (Formal)",
    "31. Meeting Notes (Informal)",
    "32. Workshop Agenda",
    "33. Workshop Output Summary/Flipchart Notes",
    "34. Raw Meeting/Interview Transcript",
    "35. Expert Interview Summary/Notes",
    "36. Client Feedback (Email/Document)",
    "37. Email Correspondence (Key Thread/Summary)",
    "38. Stakeholder Communication Log",
    "39. Generic Text Document",
    "40. User Specified (Other)"
]

PRIORITY_LEVELS = ["High", "Medium", "Low"]

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

    @classmethod
    def get_all_values(cls):
        return [item.value for item in cls]

class DocumentGroup(Enum):
    GROUP_A = "Strategic & Formal Client-Facing Deliverables/Inputs"
    GROUP_B = "Research, Analysis & Informational Inputs"
    GROUP_C = "Project Execution & Iterative Work Products"
    GROUP_D = "Conversational & Interaction Records"

CATEGORY_TO_GROUP_MAPPING = {
    DocumentCategory.STRATEGY_DOCUMENT.value: DocumentGroup.GROUP_A,
    DocumentCategory.OPERATIONAL_REPORT.value: DocumentGroup.GROUP_A,
    DocumentCategory.FINANCIAL_REPORT.value: DocumentGroup.GROUP_A,
    DocumentCategory.STATEMENT_OF_WORK.value: DocumentGroup.GROUP_A,
    DocumentCategory.PROPOSAL_DOCUMENT.value: DocumentGroup.GROUP_A,
    DocumentCategory.FORMAL_CLIENT_DELIVERABLE_REPORT.value: DocumentGroup.GROUP_A,
    DocumentCategory.FORMAL_CLIENT_DELIVERABLE_PRESENTATION.value: DocumentGroup.GROUP_A,
    DocumentCategory.CLIENT_BRIEF_RFP.value: DocumentGroup.GROUP_D, 
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
    DocumentCategory.WORKING_DRAFT_PRESENTATION.value: DocumentGroup.GROUP_C,
    DocumentCategory.WORKING_DRAFT_REPORT.value: DocumentGroup.GROUP_C,
    DocumentCategory.INTERNAL_HYPOTHESES.value: DocumentGroup.GROUP_B, 
    DocumentCategory.PRELIMINARY_ANALYSIS.value: DocumentGroup.GROUP_B, 
    DocumentCategory.PROJECT_PLAN.value: DocumentGroup.GROUP_C,
    DocumentCategory.PROJECT_TIMELINE.value: DocumentGroup.GROUP_C,
    DocumentCategory.RISK_REGISTER.value: DocumentGroup.GROUP_C,
    DocumentCategory.SANITIZED_CASE_STUDY.value: DocumentGroup.GROUP_C,
    DocumentCategory.LESSONS_LEARNED.value: DocumentGroup.GROUP_C,
    DocumentCategory.INTERNAL_PROCESS.value: DocumentGroup.GROUP_C,
    DocumentCategory.MEETING_MINUTES_FORMAL.value: DocumentGroup.GROUP_D,
    DocumentCategory.MEETING_NOTES_INFORMAL.value: DocumentGroup.GROUP_D,
    DocumentCategory.WORKSHOP_AGENDA.value: DocumentGroup.GROUP_D,
    DocumentCategory.WORKSHOP_OUTPUT.value: DocumentGroup.GROUP_D,
    DocumentCategory.RAW_TRANSCRIPT.value: DocumentGroup.GROUP_D,
    DocumentCategory.EXPERT_INTERVIEW.value: DocumentGroup.GROUP_D,
    DocumentCategory.CLIENT_FEEDBACK.value: DocumentGroup.GROUP_D,
    DocumentCategory.EMAIL_CORRESPONDENCE.value: DocumentGroup.GROUP_D,
    DocumentCategory.STAKEHOLDER_COMMUNICATION.value: DocumentGroup.GROUP_D,
    DocumentCategory.GENERIC_TEXT.value: DocumentGroup.GROUP_D, 
    DocumentCategory.USER_SPECIFIED.value: DocumentGroup.GROUP_D 
}

