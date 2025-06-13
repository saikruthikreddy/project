import sys
sys.path.append('/workspace/ProjectKnowledgeGiani/')

import logging
import gradio as gr
from giani_pkb.utils.constants import DOCUMENT_TYPES, AI_CLASSIFICATIONS, PRIORITY_LEVELS
import os
import json
import uuid
from giani_pkb.utils.exceptions import APIError, FileProcessingError, ParsingError, ConfigurationError
from datetime import datetime
import mimetypes
import google.generativeai as genai
import pandas as pd
import docx
import PyPDF2
from pathlib import Path
import shutil
# from dotenv import load_dotenv # This line will be removed in the next block # Actually removed now
from giani_pkb.utils.config import GEMINI_API_KEY, GEMINI_FLASH_MODEL
# from giani_pkb.utils.prompt_loader import load_prompt_template # Removed as unused
from giani_pkb.preprocessing.Processing import MainProcessing
from giani_pkb.core.metadata_manager import MetadataManagerService
from giani_pkb.core.models import DocumentMetadata
from giani_pkb.core.classification_service import ClassificationService # Added import

logger = logging.getLogger(__name__)

# Load environment variables
# load_dotenv() # Removed

# Configure Gemini API
# api_key = os.getenv("GEMINI_API_KEY") # Removed
# if not api_key: # Removed
    # raise ValueError("GEMINI_API_KEY environment variable not found. Please set it in your .env file") # Removed

genai.configure(api_key=GEMINI_API_KEY)

# Document type categories
# DOCUMENT_TYPES = [ ... ] # Removed, now imported from constants

# AI Classification categories
# AI_CLASSIFICATIONS = [ ... ] # Removed, now imported from constants

# PRIORITY_LEVELS = ["High", "Medium", "Low"] # Removed, now imported from constants

# Create base directories
BASE_DIR = "data/uploaded_documents" # Updated base directory for uploaded files
# MASTER_METADATA_PATH = os.path.join(BASE_DIR, "master_metadata.json") # Removed

# Instantiate MetadataManagerService
# This service will now handle all master metadata operations.
# Its own __init__ will default to "data/master_metadata.json" # Updated comment
metadata_manager_service = MetadataManagerService()
classification_service = ClassificationService() # Added instantiation


for doc_type in DOCUMENT_TYPES:
    os.makedirs(os.path.join(BASE_DIR, doc_type), exist_ok=True)

# Global storage for session data
session_data = {}

# load_master_metadata, save_master_metadata, update_master_metadata functions removed.
# Calls will be replaced with metadata_manager_service methods.

def get_master_metadata_summary():
    """Get a summary of the master metadata for display using MetadataManagerService."""
    # This function now calls the service's method that returns a string.
    return metadata_manager_service.get_master_metadata_summary_text()

def extract_text_preview(file_path, max_chars=1000):
    """Extract text preview from various file types"""
    try:
        processor=MainProcessing(api_key=GEMINI_API_KEY)
        content=processor.process_files(file_path)
        return content[:5000] # Return up to 5000 characters for preview
    except Exception as e:
        raise FileProcessingError(f"Error extracting preview from {file_path}: {str(e)}", filepath=file_path)

# Removed get_gemini_prompt function
# Removed classify_document_with_ai function

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

        # AI classification using ClassificationService
        # The service now also returns the prompt text used.
        original_filename = os.path.basename(file.name)
        ai_classification, ai_purpose, gemini_prompt_text = classification_service.classify_document(
            original_filename,
            text_preview
        )

        # Store file data including the prompt
        file_data = {
            "original_filename": original_filename,
            "file_path": file.name, # This is temp path of uploaded file
            "file_size": file_size,
            "mime_type": mime_type,
            "text_preview": text_preview,
            "gemini_prompt": gemini_prompt_text, # Use prompt from service
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
    """Save document to the appropriate folder with metadata and update master metadata using MetadataManagerService."""
    if not session_id or session_id not in session_data:
        return "Error: No active session found", get_master_metadata_summary()

    try:
        file_data = None
        for data in session_data[session_id]:
            if data["original_filename"] == selected_file or len(session_data[session_id]) == 1:
                file_data = data
                break

        if not file_data:
            return "Error: File not found in session", get_master_metadata_summary()

        dest_dir = os.path.join(BASE_DIR, doc_type) # doc_type is categoryFolder
        os.makedirs(dest_dir, exist_ok=True) # Ensure directory exists
        dest_path = os.path.join(dest_dir, file_data["original_filename"])

        shutil.copy2(file_data["file_path"], dest_path)

        metadata_filename = f"{Path(file_data['original_filename']).stem}_metadata.json"
        individual_metadata_path = os.path.join(dest_dir, metadata_filename)

        # Create DocumentMetadata object
        doc_meta_obj = DocumentMetadata(
            id=str(uuid.uuid4()), # Generate new ID here for the object
            originalFilename=file_data["original_filename"],
            fileSize=file_data["file_size"],
            fileMimeType=file_data["mime_type"],
            dateAddedToGiani=datetime.now().isoformat(), # Overwrites if already set in file_data
            userID=file_data["user_id"],
            projectID=file_data["project_id"],
            textPreview=file_data["text_preview"],
            finalCategory=ai_classification, # From UI
            finalPurpose=purpose, # From UI
            priority=priority, # From UI
            finalizedAt=datetime.now().isoformat(), # Set finalization time
            storagePath=dest_path, # Actual storage path
            categoryFolder=doc_type, # Document type from UI used as category folder
            storedFilename=individual_metadata_path, # Path to the individual metadata JSON
            savedAt=datetime.now().isoformat() # Set saved time
            # tempFilePath, processedContent, extractedText are not directly handled here, defaults in DocumentMetadata
        )

        # Save individual metadata file (using fields from DocumentMetadata object)
        individual_metadata_content = {
            "document_id": doc_meta_obj.id,
            "dateAddedToGiani": doc_meta_obj.dateAddedToGiani,
            "originalFilename": doc_meta_obj.originalFilename,
            "storagePath": doc_meta_obj.storagePath,
            "fileSize": doc_meta_obj.fileSize,
            "fileMimeType": doc_meta_obj.fileMimeType,
            "userID": doc_meta_obj.userID,
            "projectID": doc_meta_obj.projectID,
            "categoryFolder": doc_meta_obj.categoryFolder,
            "finalCategory": doc_meta_obj.finalCategory,
            "finalPurpose": doc_meta_obj.finalPurpose,
            "priority": doc_meta_obj.priority,
            "geminiPrompt": file_data.get("gemini_prompt", ""), # Keep gemini_prompt from session if available
            "textPreview": doc_meta_obj.textPreview,
            "storedFilename": doc_meta_obj.storedFilename,
            "finalizedAt": doc_meta_obj.finalizedAt,
            "savedAt": doc_meta_obj.savedAt
        }
        with open(individual_metadata_path, 'w') as f:
            json.dump(individual_metadata_content, f, indent=2)

        # Update master metadata using the service
        doc_id_from_service = metadata_manager_service.update_master_metadata(doc_meta_obj)

        updated_summary = get_master_metadata_summary() # Uses service

        return f"✅ Document successfully saved to '{doc_type}' folder with metadata (ID: {doc_id_from_service[:8]}...)", updated_summary

    except (IOError, FileNotFoundError) as e:
        raise FileProcessingError(f"Error during file operation in save_document: {str(e)}", filepath=file_data.get("file_path", "Unknown path"))
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
    # Configure basic logging for the application
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout) # Ensure logs go to stdout
        ]
    )

    # Check if API key is configured
    try:
        # Test API connection
        genai.GenerativeModel(GEMINI_FLASH_MODEL) # Test instantiation
        logger.info("Gemini API configured successfully and model available.")
    except Exception as e:
        logger.error(f"Gemini API configuration error or model ({GEMINI_FLASH_MODEL}) unavailable: {e}")
        logger.error("Please ensure GEMINI_API_KEY is correctly set and the model name is valid.")
        # Depending on severity, you might choose to exit or let Gradio app launch with limited functionality.
        # For now, it will continue to launch the app.

    # Initialize master metadata on startup using the service
    # The service's load_master_metadata will create if not exists.
    try:
        master_metadata = metadata_manager_service.load_master_metadata()
        logger.info(f"Master metadata initialized/loaded with {master_metadata.get('total_documents', 0)} documents.")
    except Exception as e:
        logger.error(f"Failed to initialize/load master metadata: {e}")
        # Handle cases where metadata cannot be loaded, perhaps by initializing an empty structure
        # For now, the app might fail later if metadata_manager_service relies on this.

    app.launch(server_name="0.0.0.0", server_port=7860, share=True)
