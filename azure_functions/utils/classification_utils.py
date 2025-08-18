import logging

def fallback_classification(filename: str, logger: logging.Logger = None) -> tuple[str, str]:
    """
    Provides a fallback classification based on filename patterns.
    Returns (classification, purpose)
    """
    if logger:
        logger.info(f"Executing fallback classification for filename: {filename}")
    filename_lower = filename.lower()
    classification = "39. Generic Text Document"
    purpose = "This document contains information relevant to the consulting project that requires further analysis to determine its specific role and contribution to the engagement."

    if any(word in filename_lower for word in ['strategy', 'strategic']):
        classification = "1. Strategy Document/Deck"
        purpose = "This document appears to contain strategic analysis and recommendations for business decision-making. It likely includes market insights, competitive positioning, and strategic options for the client's consideration."
    elif any(word in filename_lower for word in ['financial', 'finance', 'budget', 'cost', 'revenue', 'expenses', 'p&l', 'balance sheet']):
        classification = "3. Financial Report/Analysis Deck"
        purpose = "This document contains financial analysis and data relevant to the consulting engagement. It provides quantitative insights to support business recommendations and decision-making processes."
    elif any(word in filename_lower for word in ['meeting minutes', 'minutes of meeting', 'meeting notes', 'action items']):
        classification = "30. Meeting Minutes (Formal)"
        purpose = "This document captures key discussions, decisions, and action items from project meetings. It serves as a record of stakeholder alignment and project progress."
    elif any(word in filename_lower for word in ['market research', 'market analysis', 'industry report']):
        classification = "9. Market Research Report (Internal/External)"
        purpose = "This document provides market intelligence and research findings to inform strategic recommendations. It contains data and analysis about market conditions, trends, and opportunities."
    elif any(word in filename_lower for word in ['proposal', 'sow', 'statement of work', 'engagement letter']):
        classification = "4. Statement of Work (SoW)"
        purpose = "This document outlines the scope, deliverables, and terms of the consulting engagement. It serves as a foundational agreement between the consulting team and client."
    elif any(word in filename_lower for word in ['presentation', 'deck', 'slides', 'workshop materials']):
        classification = "20. Working Draft - Presentation Section"
        if "final" in filename_lower or "client version" in filename_lower:
            classification = "2. Client-Facing Presentation/Deck"
        purpose = "This document contains presentation materials or slides being developed for client communication. It represents work-in-progress content for stakeholder engagement."
    elif any(word in filename_lower for word in ['project plan', 'timeline', 'schedule', 'gantt chart', 'work plan']):
        classification = "24. Project Plan Document"
        purpose = "This document outlines project timelines, milestones, and deliverables. It serves as a roadmap for project execution and stakeholder alignment."
    elif any(word in filename_lower for word in ['data', 'dataset', 'raw data', '.csv', '.xlsx', '.xls', 'spreadsheet']):
        classification = "10. Market Data Dump/Raw Data File"
        purpose = "This document contains raw data or datasets that will be analyzed to support consulting recommendations. It provides the foundational information for quantitative analysis."
    elif any(word in filename_lower for word in ['interview notes', 'expert interview', 'stakeholder interview']):
        classification = "31. Interview Notes/Transcript"
        purpose = "This document contains notes or transcripts from interviews conducted for the project. It provides qualitative insights and stakeholder perspectives."
    elif any(word in filename_lower for word in ['survey results', 'questionnaire data']):
        classification = "11. Survey Data/Results"
        purpose = "This document contains data or results from surveys conducted as part of the project. It provides quantitative or qualitative feedback from a wider audience."

    if logger:
        logger.info(f"Fallback classification for {filename}: {classification}")
    return classification, purpose