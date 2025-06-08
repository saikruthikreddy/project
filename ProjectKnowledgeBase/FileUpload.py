import gradio as gr
import os
import json
import uuid
from datetime import datetime
import mimetypes
import google.generativeai as genai
import pandas as pd
import docx
import PyPDF2
from pathlib import Path
import shutil
from dotenv import load_dotenv
from preprocessing.Processing import MainProcessing

# Load environment variables
load_dotenv()

# Configure Gemini API
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY environment variable not found. Please set it in your .env file")

genai.configure(api_key=api_key)

# Document type categories
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

# AI Classification categories
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

# Create base directories
BASE_DIR = "uploaded_documents"
MASTER_METADATA_PATH = os.path.join(BASE_DIR, "master_metadata.json")

for doc_type in DOCUMENT_TYPES:
    os.makedirs(os.path.join(BASE_DIR, doc_type), exist_ok=True)

# Global storage for session data
session_data = {}

def load_master_metadata():
    """Load existing master metadata or create new one"""
    if os.path.exists(MASTER_METADATA_PATH):
        try:
            with open(MASTER_METADATA_PATH, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            pass
    
    # Create new master metadata structure
    return {
        "metadata_version": "1.0",
        "created_date": datetime.now().isoformat(),
        "last_updated": datetime.now().isoformat(),
        "total_documents": 0,
        "documents": [],
        "statistics": {
            "document_types": {},
            "ai_classifications": {},
            "priority_levels": {},
            "file_types": {}
        }
    }

def save_master_metadata(master_metadata):
    """Save master metadata to file"""
    master_metadata["last_updated"] = datetime.now().isoformat()
    try:
        with open(MASTER_METADATA_PATH, 'w') as f:
            json.dump(master_metadata, f, indent=2)
    except Exception as e:
        print(f"Error saving master metadata: {e}")

def update_master_metadata(document_metadata):
    """Update master metadata with new document information"""
    master_metadata = load_master_metadata()
    
    # Generate unique document ID
    doc_id = str(uuid.uuid4())
    
    # Create document entry for master metadata
    document_entry = {
        "document_id": doc_id,
        "original_filename": document_metadata["originalFilename"],
        "file_path": document_metadata.get("file_path", ""),
        "document_type": document_metadata["documentType"],
        "ai_classification": document_metadata["aiClassification"],
        "priority": document_metadata["priority"],
        "file_size": document_metadata["fileSize"],
        "file_mime_type": document_metadata["fileMimeType"],
        "date_added": document_metadata["dateAddedToGiani"],
        "user_id": document_metadata["userID"],
        "project_id": document_metadata["projectID"],
        "document_purpose": document_metadata["documentPurpose"],
        "metadata_file_path": document_metadata.get("metadata_file_path", "")
    }
    
    # Add to documents list
    master_metadata["documents"].append(document_entry)
    master_metadata["total_documents"] = len(master_metadata["documents"])
    
    # Update statistics
    stats = master_metadata["statistics"]
    
    # Document types
    doc_type = document_metadata["documentType"]
    stats["document_types"][doc_type] = stats["document_types"].get(doc_type, 0) + 1
    
    # AI classifications
    ai_class = document_metadata["aiClassification"]
    stats["ai_classifications"][ai_class] = stats["ai_classifications"].get(ai_class, 0) + 1
    
    # Priority levels
    priority = document_metadata["priority"]
    stats["priority_levels"][priority] = stats["priority_levels"].get(priority, 0) + 1
    
    # File types
    file_ext = Path(document_metadata["originalFilename"]).suffix.lower()
    stats["file_types"][file_ext] = stats["file_types"].get(file_ext, 0) + 1
    
    # Save updated master metadata
    save_master_metadata(master_metadata)
    
    return doc_id

def get_master_metadata_summary():
    """Get a summary of the master metadata for display"""
    master_metadata = load_master_metadata()
    
    summary = f"""
    📊 **Document Library Summary**
    
    **Total Documents**: {master_metadata['total_documents']}
    **Last Updated**: {master_metadata.get('last_updated', 'Never')}
    
    **Document Types**:
    """
    
    for doc_type, count in master_metadata["statistics"]["document_types"].items():
        summary += f"\n  • {doc_type}: {count}"
    
    summary += "\n\n**AI Classifications**:"
    for ai_class, count in sorted(master_metadata["statistics"]["ai_classifications"].items()):
        summary += f"\n  • {ai_class}: {count}"
    
    summary += "\n\n**Priority Distribution**:"
    for priority, count in master_metadata["statistics"]["priority_levels"].items():
        summary += f"\n  • {priority}: {count}"
    
    return summary

def extract_text_preview(file_path, max_chars=1000):
    """Extract text preview from various file types"""
    try:
        processor=MainProcessing()
        content=processor.process_files(file_path)
        return content[:5000]
    except Exception as e:
        return f"Error extracting preview: {str(e)}"

def get_gemini_prompt(filename, text_preview):
    """Generate the prompt that will be sent to Gemini AI"""
    classification_list = "\n".join([f"{i+1}. {cat.split('. ', 1)[1] if '. ' in cat else cat}" for i, cat in enumerate(AI_CLASSIFICATIONS)])
    
    prompt = f"""You are an AI assistant helping classify documents for a management consulting project. 

Based on the filename "{filename}" and this text preview:
"{text_preview[:5000]}"

Please classify this document into ONE of these categories (respond with just the number and title exactly as shown):

{classification_list}

Also provide a 1-3 sentence description of the document's purpose for this management consulting project.

Format your response exactly as:
CLASSIFICATION: [number]. [category name]
PURPOSE: [1-3 sentences describing the document's purpose]

Be precise and match the category names exactly as listed above."""
    
    return prompt

def classify_document_with_ai(filename, text_preview):
    """Use Gemini AI to classify the document"""
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        # Get the prompt using the dedicated function
        prompt = get_gemini_prompt(filename, text_preview)
        
        response = model.generate_content(prompt)
        print('GEMINI API CALLED')
        ai_response = response.text.strip()
        print(ai_response)
        
        # Parse the response
        lines = ai_response.split('\n')
        classification = "39. Generic Text Document"
        purpose = "Document classification pending - unable to determine specific purpose from available content."
        
        for line in lines:
            line = line.strip()
            if line.startswith('CLASSIFICATION:'):
                classification_text = line.replace('CLASSIFICATION:', '').strip()
                # Validate that the classification matches one of our categories
                for cat in AI_CLASSIFICATIONS:
                    if classification_text in cat or cat.split('. ', 1)[1] in classification_text:
                        classification = cat
                        break
            elif line.startswith('PURPOSE:'):
                purpose = line.replace('PURPOSE:', '').strip()
        
        return classification, purpose
        
    except Exception as e:
        print(f"Error in AI classification: {str(e)}")
        # Fallback classification based on filename patterns
        filename_lower = filename.lower()
        
        if any(word in filename_lower for word in ['strategy', 'strategic']):
            classification = "1. Strategy Document/Deck"
            purpose = "This document appears to contain strategic analysis and recommendations for business decision-making. It likely includes market insights, competitive positioning, and strategic options for the client's consideration."
        elif any(word in filename_lower for word in ['financial', 'finance', 'budget', 'cost', 'revenue']):
            classification = "3. Financial Report/Analysis Deck"
            purpose = "This document contains financial analysis and data relevant to the consulting engagement. It provides quantitative insights to support business recommendations and decision-making processes."
        elif any(word in filename_lower for word in ['meeting', 'minutes', 'notes']):
            classification = "30. Meeting Minutes (Formal)"
            purpose = "This document captures key discussions, decisions, and action items from project meetings. It serves as a record of stakeholder alignment and project progress."
        elif any(word in filename_lower for word in ['market', 'research', 'analysis']):
            classification = "9. Market Research Report (Internal/External)"
            purpose = "This document provides market intelligence and research findings to inform strategic recommendations. It contains data and analysis about market conditions, trends, and opportunities."
        elif any(word in filename_lower for word in ['proposal', 'sow', 'statement of work']):
            classification = "4. Statement of Work (SoW)"
            purpose = "This document outlines the scope, deliverables, and terms of the consulting engagement. It serves as a foundational agreement between the consulting team and client."
        elif any(word in filename_lower for word in ['presentation', 'deck', 'slides']):
            classification = "20. Working Draft - Presentation Section"
            purpose = "This document contains presentation materials or slides being developed for client communication. It represents work-in-progress content for stakeholder engagement."
        elif any(word in filename_lower for word in ['plan', 'timeline', 'schedule']):
            classification = "24. Project Plan Document"
            purpose = "This document outlines project timelines, milestones, and deliverables. It serves as a roadmap for project execution and stakeholder alignment."
        elif any(word in filename_lower for word in ['data', 'dataset', 'csv', 'excel']):
            classification = "10. Market Data Dump/Raw Data File"
            purpose = "This document contains raw data or datasets that will be analyzed to support consulting recommendations. It provides the foundational information for quantitative analysis."
        else:
            classification = "39. Generic Text Document"
            purpose = "This document contains information relevant to the consulting project that requires further analysis to determine its specific role and contribution to the engagement."
            
        return classification, purpose

def process_file_upload(files, progress=gr.Progress()):
    """Process uploaded files and return session data"""
    if not files:
        return "No files uploaded", "", "", "", "", "", get_master_metadata_summary()
    
    session_id = str(uuid.uuid4())
    session_data[session_id] = []
    
    progress(0, desc="Processing files...")
    
    for i, file in enumerate(files):
        progress((i + 1) / len(files), desc=f"Processing {file.name}...")
        
        # Generate metadata
        file_size = os.path.getsize(file.name)
        mime_type = mimetypes.guess_type(file.name)[0] or "unknown"
        
        # Extract text preview
        text_preview = extract_text_preview(file.name)
        
        # AI classification
        ai_classification, ai_purpose = classify_document_with_ai(os.path.basename(file.name), text_preview)
        
        # Store file data including the prompt
        file_data = {
            "original_filename": os.path.basename(file.name),
            "file_path": file.name,
            "file_size": file_size,
            "mime_type": mime_type,
            "text_preview": text_preview,
            "gemini_prompt": get_gemini_prompt(os.path.basename(file.name), text_preview),
            "ai_classification": ai_classification,
            "ai_purpose": ai_purpose,
            "date_added": datetime.now().isoformat(),
            "user_id": "user_001",  # This would come from authentication
            "project_id": "project_001"  # This would come from project context
        }
        
        session_data[session_id].append(file_data)
    
    metadata_summary = get_master_metadata_summary()
    
    if len(files) == 1:
        # Single file - populate the interface
        file_data = session_data[session_id][0]
        return (
            session_id,
            file_data["original_filename"],
            DOCUMENT_TYPES[0],  # Default selection
            gr.Dropdown(value=file_data["ai_classification"]),  # Set dropdown value
            file_data["ai_purpose"],
            "Medium",  # Default priority
            file_data["gemini_prompt"],  # Show the prompt
            metadata_summary
        )
    else:
        # Multiple files - show summary
        return (
            session_id,
            f"{len(files)} files uploaded successfully",
            DOCUMENT_TYPES[0],
            gr.Dropdown(value="Multiple files processed"),  # Set dropdown for multiple files
            f"Processed {len(files)} files for classification and organization",
            "Medium",
            "Select a specific file to view its Gemini prompt",
            metadata_summary
        )

def save_document(session_id, selected_file, doc_type, ai_classification, purpose, priority):
    """Save document to the appropriate folder with metadata and update master metadata"""
    if not session_id or session_id not in session_data:
        return "Error: No active session found", get_master_metadata_summary()
    
    try:
        # Find the file data
        file_data = None
        for data in session_data[session_id]:
            if data["original_filename"] == selected_file or len(session_data[session_id]) == 1:
                file_data = data
                break
        
        if not file_data:
            return "Error: File not found in session", get_master_metadata_summary()
        
        # Create destination path
        dest_dir = os.path.join(BASE_DIR, doc_type)
        dest_path = os.path.join(dest_dir, file_data["original_filename"])
        
        # Copy file to destination
        shutil.copy2(file_data["file_path"], dest_path)
        
        # Create metadata file path
        metadata_filename = f"{Path(file_data['original_filename']).stem}_metadata.json"
        metadata_path = os.path.join(dest_dir, metadata_filename)
        
        # Create metadata
        metadata = {
            "dateAddedToGiani": datetime.now().isoformat(),
            "originalFilename": file_data["original_filename"],
            "file_path": dest_path,
            "fileSize": file_data["file_size"],
            "fileMimeType": file_data["mime_type"],
            "userID": file_data["user_id"],
            "projectID": file_data["project_id"],
            "documentType": doc_type,
            "aiClassification": ai_classification,
            "documentPurpose": purpose,
            "priority": priority,
            "geminiPrompt": file_data["gemini_prompt"],
            "textPreview": file_data["text_preview"][:5000] + "..." if len(file_data["text_preview"]) > 5000 else file_data["text_preview"],
            "metadata_file_path": metadata_path
        }
        
        # Save individual metadata file
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        # Update master metadata
        doc_id = update_master_metadata(metadata)
        
        # Get updated summary
        updated_summary = get_master_metadata_summary()
        
        return f"✅ Document successfully saved to '{doc_type}' folder with metadata (ID: {doc_id[:8]}...)", updated_summary
        
    except Exception as e:
        return f"❌ Error saving document: {str(e)}", get_master_metadata_summary()

def update_file_selection(session_id):
    """Update file selection dropdown based on session"""
    if not session_id or session_id not in session_data:
        return gr.Dropdown(choices=[], value=None)
    
    filenames = [data["original_filename"] for data in session_data[session_id]]
    return gr.Dropdown(choices=filenames, value=filenames[0] if filenames else None)

def update_file_details(session_id, selected_file):
    """Update file details when selection changes"""
    if not session_id or session_id not in session_data or not selected_file:
        return gr.Dropdown(value=None), "", "Medium", ""
    
    for data in session_data[session_id]:
        if data["original_filename"] == selected_file:
            return (
                gr.Dropdown(value=data["ai_classification"]), 
                data["ai_purpose"], 
                "Medium",
                data["gemini_prompt"]
            )
    
    return gr.Dropdown(value=None), "", "Medium", ""

# Create Gradio interface
with gr.Blocks(title="Document Upload & Classification System", theme=gr.themes.Soft()) as app:
    gr.Markdown("""
    # 📄 Document Upload & Classification System
    Upload documents for your management consulting project. The system will automatically classify them and help organize them appropriately.
    """)
    
    # Hidden session state
    session_state = gr.State("")
    
    with gr.Row():
        with gr.Column(scale=2):
            # File upload section
            gr.Markdown("### 📤 Upload Documents")
            file_upload = gr.File(
                label="Select Files",
                file_count="multiple",
                file_types=[".pdf", ".docx", ".doc", ".txt", ".csv", ".xlsx", ".xls", ".pptx"]
            )
            
            upload_btn = gr.Button("Process Files", variant="primary", size="lg")
            upload_status = gr.Textbox(label="Upload Status", interactive=False)
            
        with gr.Column(scale=3):
            # Document details section
            gr.Markdown("### 📋 Document Details & Classification")
            
            file_selector = gr.Dropdown(
                label="Select File (for multiple uploads)",
                choices=[],
                interactive=True
            )
            
            with gr.Row():
                with gr.Column():
                    doc_type = gr.Dropdown(
                        label="Document Type Category",
                        choices=DOCUMENT_TYPES,
                        value=DOCUMENT_TYPES[0],
                        interactive=True,
                        info="Select the document type for folder organization"
                    )
                    
                with gr.Column():
                    ai_classification = gr.Dropdown(
                        label="AI Classification",
                        choices=AI_CLASSIFICATIONS,
                        interactive=True,
                        info="AI-generated classification (editable)"
                    )
            
            purpose = gr.Textbox(
                label="Document Purpose",
                lines=3,
                interactive=True,
                info="Edit the AI-generated purpose if needed"
            )
            
            priority = gr.Dropdown(
                label="Document Priority",
                choices=PRIORITY_LEVELS,
                value="Medium",
                interactive=True
            )
            
            save_btn = gr.Button("Save Document", variant="secondary", size="lg")
            save_status = gr.Textbox(label="Save Status", interactive=False)
    
    # Master Metadata Summary Section
    with gr.Row():
        with gr.Column():
            gr.Markdown("### 📊 Document Library Overview")
            master_metadata_display = gr.Markdown(
                value=get_master_metadata_summary(),
                label="Library Statistics"
            )
    
    # Gemini Prompt Display Section
    with gr.Row():
        with gr.Column():
            gr.Markdown("### 🤖 Gemini AI Prompt Preview")
            gemini_prompt_display = gr.Textbox(
                label="Prompt Sent to Gemini AI",
                lines=15,
                interactive=False,
                info="This shows the exact prompt that was/will be sent to Gemini AI for classification",
                placeholder="Upload and select a file to see the Gemini prompt..."
            )
    
    # Event handlers
    upload_btn.click(
        fn=process_file_upload,
        inputs=[file_upload],
        outputs=[session_state, upload_status, doc_type, ai_classification, purpose, priority, gemini_prompt_display, master_metadata_display]
    ).then(
        fn=update_file_selection,
        inputs=[session_state],
        outputs=[file_selector]
    )
    
    file_selector.change(
        fn=update_file_details,
        inputs=[session_state, file_selector],
        outputs=[ai_classification, purpose, priority, gemini_prompt_display]
    )
    
    save_btn.click(
        fn=save_document,
        inputs=[session_state, file_selector, doc_type, ai_classification, purpose, priority],
        outputs=[save_status, master_metadata_display]
    )
    
    # Instructions
    with gr.Accordion("📖 Instructions", open=False):
        gr.Markdown("""
        ### How to use this system:
        
        1. **Upload Files**: Select one or more documents using the file upload area
        2. **Process Files**: Click "Process Files" to analyze and classify your documents
        3. **Review & Edit Classification**: 
           - Check the AI-generated classification and edit if needed
           - Choose the document type category for folder organization
        4. **Edit Purpose**: Modify the document purpose description if needed
        5. **Set Priority**: Select the document priority level
        6. **Save Document**: Click "Save Document" to finalize and store the document
        
        ### Supported File Types:
        - PDF documents (.pdf)
        - Word documents (.docx, .doc)
        - Text files (.txt)
        - Excel files (.xlsx, .xls)
        - CSV files (.csv)
        - PowerPoint files (.pptx)
        
        ### Enhanced Features:
        
        - **Master Metadata**: All documents are tracked in a centralized master_metadata.json file
        - **Library Overview**: Real-time statistics and overview of your document library
        - **AI Transparency**: View the exact prompt sent to Gemini AI for each document
        - **Full Control**: Edit both document type categories and AI classifications
        - **Intelligent Fallback**: System uses filename-based classification if AI is unavailable
        - **Complete Metadata**: All classifications, user choices, and AI prompts are saved
        - **Unique Document IDs**: Each document gets a unique identifier for tracking
        """)

if __name__ == "__main__":
    # Check if API key is configured
    try:
        # Test API connection
        test_model = genai.GenerativeModel('gemini-1.5-flash')
        print("✅ Gemini API configured successfully")
    except Exception as e:
        print(f"❌ Gemini API configuration error: {e}")
        print("Please ensure GEMINI_API_KEY is set in your .env file")
    
    # Initialize master metadata on startup
    master_metadata = load_master_metadata()
    print(f"📊 Master metadata initialized with {master_metadata['total_documents']} documents")
    
    app.launch(server_name="0.0.0.0", server_port=7860, share=True)