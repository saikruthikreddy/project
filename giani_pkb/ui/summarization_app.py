import sys
sys.path.append('/home/user/projectknowledge-2')

import gradio as gr
import json
import logging
import os 
from typing import Dict, List, Any, Optional 
from giani_pkb.core.summarization_service import SummarizationService
from giani_pkb.core.metadata_manager import MetadataManagerService
from giani_pkb.core.models import DocumentMetadata


summarization_service: Optional[SummarizationService] = None
metadata_manager_service: Optional[MetadataManagerService] = None
documents_list: List[DocumentMetadata] = []

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

initialization_status = "App not initialized."

def initialize_app():
    """Initialize the application services and load documents."""
    global summarization_service, metadata_manager_service, documents_list, initialization_status

    logger.info("Attempting to initialize the Summarization application...")
    initialization_status = "Initializing services..."
    try:
        metadata_manager_service = MetadataManagerService()
        summarization_service = SummarizationService()

        initialization_status = "Services initialized. Loading documents..."
        logger.info("Services initialized. Loading documents...")

        loaded_docs = metadata_manager_service.get_all_document_metadata()
        documents_list = loaded_docs 

        count = len(documents_list)
        initialization_status = f"Initialization complete. Loaded {count} documents."
        logger.info(f"Initialization complete. Loaded {count} documents.")
        if not documents_list:
            logger.warning("No documents were loaded from the metadata manager.")
            initialization_status += " (Warning: No documents found)"

        return initialization_status
    except Exception as e:
        initialization_status = f"Error during initialization: {str(e)}"
        logger.error(f"Error during application initialization: {e}", exc_info=True)
        summarization_service = None
        metadata_manager_service = None
        documents_list = []
        return initialization_status

def get_document_choices():
    """Get list of document choices for dropdown, using DocumentMetadata objects."""
    global documents_list

    if not documents_list: 
        logger.warning("get_document_choices called but documents_list is empty.")
        return gr.Dropdown(choices=[], value=None)

    choices = []
    for doc in documents_list:
        doc_id_short = doc.id[:8] if doc.id else "N/A"
        choices.append(f"{doc.originalFilename} (ID: {doc_id_short})")

    logger.info(f"Populated {len(choices)} document choices for dropdown.")
    return gr.Dropdown(choices=choices, value=choices[0] if choices else None)


def find_document_by_display_name(display_name: str) -> Optional[DocumentMetadata]:
    """Finds a DocumentMetadata object from documents_list based on its display name."""
    global documents_list
    if not display_name or not documents_list:
        return None

    try:
        id_part = display_name.split('(ID: ')[1][:-1] 
    except IndexError:
        logger.warning(f"Could not parse ID from display name: {display_name}")
        return None

    for doc in documents_list:
        if doc.id and doc.id.startswith(id_part):
            return doc
    logger.warning(f"Document with ID starting {id_part} (from {display_name}) not found in documents_list.")
    return None

def process_selected_document(selected_document_display_name: str):
    """Process the selected document and return formatted results and logs."""
    global summarization_service

    logger.info(f"Processing request for document: {selected_document_display_name}")
    if not summarization_service:
        logger.error("Summarization service not initialized.")
        return "Error: Summarization service not initialized. Please initialize the app.", "Service not ready."

    if not selected_document_display_name:
        return "Please select a document from the list.", "No document selected."

    selected_doc_object = find_document_by_display_name(selected_document_display_name)

    if not selected_doc_object:
        logger.warning(f"Document not found for display name: {selected_document_display_name}")
        return f"Error: Document '{selected_document_display_name}' not found.", "Document not found."

    logger.info(f"Found document: {selected_doc_object.originalFilename} (ID: {selected_doc_object.id}). Initiating summarization.")

    try:
        summarization_result = summarization_service.summarize_document(selected_doc_object)

        api_logs_summary_data = summarization_service.get_api_call_summary()

        if summarization_result:
            formatted_result = json.dumps(summarization_result, indent=2, ensure_ascii=False)
            logger.info(f"Summarization successful for {selected_doc_object.originalFilename}.")
        else:
            formatted_result = "Summarization failed or returned no result. Check service logs."
            logger.warning(f"Summarization failed or returned None for {selected_doc_object.originalFilename}.")

        formatted_api_logs = f"Total API Calls: {api_logs_summary_data.get('total_api_calls', 0)}\n"
        formatted_api_logs += f"Total Prompt Characters: {api_logs_summary_data.get('total_prompt_characters', 0)}\n"
        formatted_api_logs += f"Total Response Characters: {api_logs_summary_data.get('total_response_characters', 0)}\n\n"

        for call in api_logs_summary_data.get('individual_api_calls', []):
            formatted_api_logs += (
                f"Call #: {call['call_number']} | Timestamp: {call['timestamp']} | Model: {call['model']}\n"
                f"  Prompt ({call['prompt_length']} chars): {call['prompt_preview']}\n"
                f"  Response ({call['response_length']} chars): {call['response_preview']}\n\n"
            )
        logger.debug(f"API logs for {selected_doc_object.originalFilename} processed for display.")

        return formatted_result, formatted_api_logs

    except Exception as e:
        logger.error(f"Error in process_selected_document for {selected_document_display_name}: {e}", exc_info=True)
        return f"An unexpected error occurred: {str(e)}", "Error during processing."


def show_full_prompt_for_selected_doc(selected_document_display_name: str):
    """Generates and displays the full prompt for the selected document."""
    global summarization_service
    logger.info(f"Request to show full prompt for: {selected_document_display_name}")

    if not summarization_service:
        logger.error("Summarization service not initialized for showing prompt.")
        return "Error: Summarization service not initialized."

    if not selected_document_display_name:
        return "Please select a document to view its prompt."

    selected_doc_object = find_document_by_display_name(selected_document_display_name)
    if not selected_doc_object:
        logger.warning(f"Document not found for display name (show_full_prompt): {selected_document_display_name}")
        return f"Error: Document '{selected_document_display_name}' not found."

    try:
        logger.debug(f"Extracting chunks for prompt generation: {selected_doc_object.storagePath}")
        key_document_chunks = summarization_service.extract_document_chunks(selected_doc_object.storagePath)

        if key_document_chunks.startswith("Document file not found:"):
            logger.error(f"Cannot generate prompt, file not found: {selected_doc_object.storagePath}")
            return f"Error: Document file not found at {selected_doc_object.storagePath}. Cannot generate prompt."

        logger.debug(f"Generating appropriate prompt for {selected_doc_object.originalFilename}")
        prompt_text = summarization_service.get_appropriate_prompt(selected_doc_object, key_document_chunks)

        formatted_prompt_display = (
            f"--- PROMPT FOR: {selected_doc_object.originalFilename} ---\n"
            f"Document ID: {selected_doc_object.id}\n"
            f"Category: {selected_doc_object.finalCategory}\n"
            f"Purpose: {selected_doc_object.finalPurpose}\n"
            f"--- PROMPT START ---\n\n{prompt_text}\n\n--- PROMPT END ---"
        )
        return formatted_prompt_display
    except Exception as e:
        logger.error(f"Error generating full prompt for {selected_document_display_name}: {e}", exc_info=True)
        return f"An error occurred while generating the prompt: {str(e)}"


def create_gradio_interface():
    """Creates and configures the Gradio UI for document summarization."""
    logger.info("Creating Gradio interface for Summarization App.")
    with gr.Blocks(title="Document Summarization Processor", theme=gr.themes.Soft()) as app:
        gr.Markdown("# Document Summarization Processor")
        gr.Markdown("Select a document to summarize it using the configured Gemini model and view API call details.")

        with gr.Row():
            init_status_display = gr.Textbox(
                label="App Initialization Status",
                value=initialization_status,
                interactive=False
            )
            init_btn = gr.Button("Initialize/Refresh App & Documents")

        document_dropdown = gr.Dropdown(
            label="Select Document",
            choices=[], 
            interactive=True,
            info="Choose a document from the list loaded via MetadataManagerService."
        )

        with gr.Row():
            process_btn = gr.Button("Summarize Selected Document", variant="primary")
            show_prompt_btn = gr.Button("Show Full Prompt")

        with gr.Tab("Summarization Result"):
            result_output = gr.Textbox(label="Summary JSON", lines=20, interactive=False, show_copy_button=True)

        with gr.Tab("API Call Logs"):
            logs_output = gr.Textbox(label="API Call Log Details", lines=20, interactive=False, show_copy_button=True)

        with gr.Tab("Full Prompt Preview"):
            full_prompt_display = gr.Textbox(label="Full Generated Prompt", lines=20, interactive=False, show_copy_button=True)

        def init_and_update_choices_ui():
            status = initialize_app()
            choices_dropdown = get_document_choices()
            return status, choices_dropdown

        init_btn.click(
            fn=init_and_update_choices_ui,
            outputs=[init_status_display, document_dropdown]
        )

        process_btn.click(
            fn=process_selected_document,
            inputs=[document_dropdown],
            outputs=[result_output, logs_output]
        )

        show_prompt_btn.click(
            fn=show_full_prompt_for_selected_doc,
            inputs=[document_dropdown],
            outputs=[full_prompt_display]
        )

        app.load(
            fn=init_and_update_choices_ui,
            outputs=[init_status_display, document_dropdown]
        )
        logger.info("Gradio interface created and event handlers defined.")
    return app

if __name__ == "__main__":
    logger.info("Starting Summarization App directly.")
    summarization_gradio_app = create_gradio_interface()
    summarization_gradio_app.launch(
        server_name="0.0.0.0",
        server_port=7862, 
        share=False, 
        debug=True   
    )
    logger.info("Summarization App launched on port 7862.")
