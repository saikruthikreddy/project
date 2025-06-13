import gradio as gr
import json
import os
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
import google.generativeai as genai
from dotenv import load_dotenv
from giani_pkb.utils.constants import DocumentCategory, DocumentGroup # Added
from preprocessing.Processing import MainProcessing

# Import your existing classes (ensure these are in the same directory or properly imported)
from .OldSummary import DocumentSummarizer, DocumentMetadata # DocumentCategory, DocumentGroup removed & path fixed

# load_dotenv() # Removed

class GradioDocumentSummarizer(DocumentSummarizer):
    """Extended DocumentSummarizer class with Gradio logging capabilities"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_call_logs = []
        self.current_document_logs = []
    
    def call_llm_api_with_logging(self, prompt: str, document_filename: str, max_retries: int = 3, retry_delay: float = 1.0) -> Optional[Dict[str, Any]]:
        """Enhanced version of call_llm_api that logs all API interactions"""
        self.current_document_logs = []  # Reset logs for current document
        
        for attempt in range(max_retries):
            try:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # Log the API call attempt
                call_log = {
                    "timestamp": timestamp,
                    "document": document_filename,
                    "attempt": attempt + 1,
                    "max_retries": max_retries,
                    "prompt_length": len(prompt),
                    "prompt_preview": prompt[:500] + "..." if len(prompt) > 500 else prompt,
                    "full_prompt": prompt,
                    "status": "Attempting API call",
                    "model": self.gemini_model
                }
                
                self.current_document_logs.append(call_log)
                print(f"\n📞 API Call Attempt {attempt + 1}/{max_retries} for {document_filename}")
                print(f"⏰ Timestamp: {timestamp}")
                print(f"🤖 Model: {self.gemini_model}")
                print(f"📝 Prompt length: {len(prompt)} characters")
                
                # Make the API call to Gemini
                print("🚀 Sending request to Gemini API...")
                response = self.model.generate_content(
                    prompt,
                    generation_config=self.generation_config
                )
                
                # Log successful response
                if response.text:
                    response_log = {
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "document": document_filename,
                        "attempt": attempt + 1,
                        "status": "Success",
                        "response_length": len(response.text),
                        "response_preview": response.text[:500] + "..." if len(response.text) > 500 else response.text,
                        "full_response": response.text
                    }
                    self.current_document_logs.append(response_log)
                    
                    print("✅ API call successful!")
                    print(f"📊 Response length: {len(response.text)} characters")
                    
                    # Try to parse JSON
                    try:
                        response_text = response.text.strip()
                        if response_text.startswith('```'):
                            response_text = response_text[7:]
                        if response_text.endswith('```'):
                            response_text = response_text[:-3]
                        response_text = response_text.strip()
                        
                        llm_response = json.loads(response_text)
                        llm_response["llm_used_for_processing"] = f"gemini-{self.gemini_model}"
                        
                        parse_log = {
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "document": document_filename,
                            "status": "JSON Parse Success",
                            "parsed_data": llm_response
                        }
                        self.current_document_logs.append(parse_log)
                        
                        print("✅ JSON parsing successful!")
                        
                        # Store complete logs for this document
                        self.api_call_logs.extend(self.current_document_logs)
                        
                        return llm_response
                        
                    except json.JSONDecodeError as e:
                        error_log = {
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "document": document_filename,
                            "attempt": attempt + 1,
                            "status": "JSON Parse Error",
                            "error": str(e),
                            "raw_response": response.text[:1000]
                        }
                        self.current_document_logs.append(error_log)
                        
                        print(f"❌ JSON parsing failed: {e}")
                        
                        if attempt < max_retries - 1:
                            print(f"🔄 Retrying in {retry_delay} seconds...")
                            continue
                        
            except Exception as e:
                error_log = {
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "document": document_filename,
                    "attempt": attempt + 1,
                    "status": "API Error",
                    "error": str(e)
                }
                self.current_document_logs.append(error_log)
                
                print(f"❌ API call error: {e}")
                if attempt < max_retries - 1:
                    print(f"🔄 Retrying in {retry_delay * (2 ** attempt)} seconds...")
                    continue
        
        # If we get here, all retries failed
        final_error_log = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "document": document_filename,
            "status": "Final Failure",
            "error": f"Failed after {max_retries} attempts"
        }
        self.current_document_logs.append(final_error_log)
        self.api_call_logs.extend(self.current_document_logs)
        
        print(f"💀 All {max_retries} attempts failed for {document_filename}")
        return None
    
    def process_single_document_with_logging(self, document: DocumentMetadata) -> tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        """Process a single document and return both result and logs"""
        try:
            print(f"\n🔍 Starting document processing: {document.originalFilename}")
            print(f"📁 File path: {document.storagePath}")
            print(f"🏷️ Category: {document.finalCategory}")
            print(f"🎯 Purpose: {document.finalPurpose}")
            
            # Extract document content
            print("\n📖 Extracting document content...")
            key_document_chunks = self.extract_document_chunks(document.storagePath)
            print(f"✅ Content extracted: {len(key_document_chunks)} characters")
            
            # Get appropriate prompt
            print("\n🎨 Generating prompt...")
            prompt = self.get_appropriate_prompt(document, key_document_chunks)
            group = self.get_document_group(document.finalCategory)
            print(f"✅ Prompt generated for {group.value}")
            print(f"📏 Prompt length: {len(prompt)} characters")
            
            # Call Gemini API with logging
            print("\n🚀 Calling Gemini API...")
            llm_response = self.call_llm_api_with_logging(prompt, document.originalFilename)
            
            if llm_response:
                result = {
                    "document_id": document.id,
                    "document_filename": document.originalFilename,
                    "document_category": document.finalCategory,
                    "document_group": group.value,
                    "user_note_purpose": document.finalPurpose,
                    "processing_timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "llm_analysis": llm_response
                }
                
                print(f"✅ Successfully processed: {document.originalFilename}")
                return result, self.current_document_logs
            else:
                print(f"❌ Failed to process: {document.originalFilename}")
                return None, self.current_document_logs
                
        except Exception as e:
            error_log = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "document": document.originalFilename,
                "status": "Processing Error",
                "error": str(e)
            }
            self.current_document_logs.append(error_log)
            print(f"💥 Error processing document {document.id}: {e}")
            return None, self.current_document_logs

# Global variables
summarizer = None
documents_list = []
initialization_status = "Not initialized"

def initialize_app():
    """Initialize the application and load documents"""
    global summarizer, documents_list, initialization_status
    
    try:
        initialization_status = "Initializing..."
        print("🔄 Initializing DocumentSummarizer...")
        
        summarizer = GradioDocumentSummarizer(
            gemini_api_key=None,  # Will use GEMINI_API_KEY env var
            gemini_model="gemini-1.5-pro"
        )
        
        print("📂 Loading master metadata...")
        # Load master metadata
        metadata = summarizer.load_master_metadata()
        print(f"📊 Metadata loaded: {metadata.get('totalDocuments', 0)} total documents")
        
        documents_list = []
        failed_documents = []
        
        for doc_data in metadata.get('documents', []):
            try:
                document = DocumentMetadata.from_dict(doc_data)
                display_name = f"{document.originalFilename} ({document.finalCategory})"
                documents_list.append({
                    'display_name': display_name,
                    'document': document
                })
                print(f"✅ Loaded: {display_name}")
            except Exception as e:
                failed_documents.append(f"Failed to load document: {e}")
                print(f"❌ Failed to load document: {e}")
        
        initialization_status = f"✅ Initialized successfully! Loaded {len(documents_list)} documents."
        
        if failed_documents:
            initialization_status += f"\n⚠️ {len(failed_documents)} documents failed to load."
        
        print(f"🎉 Initialization complete: {len(documents_list)} documents ready")
        return initialization_status
    
    except Exception as e:
        error_msg = f"❌ Initialization failed: {str(e)}"
        initialization_status = error_msg
        print(f"💥 Initialization error: {e}")
        return error_msg

def get_document_choices():
    """Get list of document choices for dropdown"""
    global documents_list, initialization_status
    
    print(f"📋 Getting document choices. Current status: {initialization_status}")
    print(f"📊 Documents available: {len(documents_list)}")
    
    if not documents_list:
        print("⚠️ No documents available. Trying to reinitialize...")
        init_result = initialize_app()
        print(f"🔄 Reinitialization result: {init_result}")
    
    choices = [doc['display_name'] for doc in documents_list]
    print(f"📝 Returning {len(choices)} choices")
    
    return gr.Dropdown(choices=choices, value=None if not choices else choices[0])

def process_selected_document(selected_document):
    """Process the selected document and return logs"""
    global summarizer, documents_list
    
    print(f"🎯 Processing selected document: {selected_document}")
    
    if not selected_document:
        return "❌ Please select a document.", "No document selected."
    
    if not summarizer:
        return "❌ Please initialize the app first.", "App not initialized."
    
    if not documents_list:
        return "❌ No documents loaded. Please refresh the document list.", "No documents available."
    
    # Find the selected document
    selected_doc = None
    for doc_info in documents_list:
        if doc_info['display_name'] == selected_document:
            selected_doc = doc_info['document']
            break
    
    if not selected_doc:
        available_docs = [doc['display_name'] for doc in documents_list]
        error_msg = f"❌ Document '{selected_document}' not found in loaded documents.\n\nAvailable documents:\n" + "\n".join(available_docs[:5])
        return error_msg, "Document not found in list."
    
    print(f"📄 Found document: {selected_doc.originalFilename}")
    
    # Process the document with logging
    try:
        result, logs = summarizer.process_single_document_with_logging(selected_doc)
        
        # Format logs for display
        log_text = ""
        for i, log in enumerate(logs, 1):
            log_text += f"=== LOG ENTRY {i} ===\n"
            log_text += f"⏰ Timestamp: {log.get('timestamp', 'N/A')}\n"
            log_text += f"📊 Status: {log.get('status', 'N/A')}\n"
            
            if 'attempt' in log:
                log_text += f"🔄 Attempt: {log['attempt']}/{log.get('max_retries', 'N/A')}\n"
            
            if 'prompt_length' in log:
                log_text += f"📝 Prompt Length: {log['prompt_length']} chars\n"
            
            if 'response_length' in log:
                log_text += f"📄 Response Length: {log['response_length']} chars\n"
            
            if 'error' in log:
                log_text += f"❌ Error: {log['error']}\n"
            
            if 'response_preview' in log:
                log_text += f"📋 Response Preview:\n{log['response_preview']}\n"
            
            log_text += "\n" + "="*80 + "\n\n"
        
        # Format result
        if result:
            result_text = "✅ PROCESSING SUCCESSFUL!\n\n"
            result_text += json.dumps(result, indent=2, ensure_ascii=False)
        else:
            result_text = "❌ Processing failed. Check logs for details."
        
        return result_text, log_text
        
    except Exception as e:
        error_msg = f"💥 Error processing document: {str(e)}"
        print(error_msg)
        return error_msg, f"Processing error: {str(e)}"

def show_full_prompt(selected_document):
    """Show the full prompt that would be sent to Gemini"""
    global summarizer, documents_list
    
    if not selected_document:
        return "❌ Please select a document."
    
    if not summarizer:
        return "❌ Please initialize the app first."
    
    if not documents_list:
        return "❌ No documents loaded. Please refresh the document list."
    
    # Find the selected document
    selected_doc = None
    for doc_info in documents_list:
        if doc_info['display_name'] == selected_document:
            selected_doc = doc_info['document']
            break
    
    if not selected_doc:
        return "❌ Document not found."
    
    try:
        # Extract document content
        key_document_chunks = summarizer.extract_document_chunks(selected_doc.storagePath)
        
        # Get appropriate prompt
        prompt = summarizer.get_appropriate_prompt(selected_doc, key_document_chunks)
        
        return f"🎨 FULL PROMPT FOR: {selected_doc.originalFilename}\n\n" + prompt
        
    except Exception as e:
        return f"❌ Error generating prompt: {str(e)}"

# Create Gradio interface
def create_gradio_interface():
    with gr.Blocks(title="Gemini API Document Processor", theme=gr.themes.Soft()) as app:
        gr.Markdown("# 🚀 Gemini API Document Processor")
        gr.Markdown("Monitor and analyze Gemini API calls for document processing")
        
        # State variable to track initialization
        init_state = gr.State(value="Not initialized")
        
        # Initialization section
        with gr.Row():
            init_btn = gr.Button("🔄 Initialize App", variant="primary")
            init_status = gr.Textbox(label="Initialization Status", value="Click 'Initialize App' to start", interactive=False)
        
        # Document selection section
        with gr.Row():
            document_dropdown = gr.Dropdown(
                label="📁 Select Document",
                choices=[],
                value=None,
                interactive=True,
                info="Select a document to process"
            )
            refresh_btn = gr.Button("🔄 Refresh Document List")
        
        # Action buttons
        with gr.Row():
            process_btn = gr.Button("🚀 Process Document & Show API Calls", variant="primary")
            show_prompt_btn = gr.Button("👁️ Show Full Prompt", variant="secondary")
        
        # Results section
        with gr.Row():
            with gr.Column():
                gr.Markdown("### 📊 Processing Result")
                result_output = gr.Textbox(
                    label="Result",
                    lines=20,
                    max_lines=50,
                    interactive=False,
                    show_copy_button=True
                )
            
            with gr.Column():
                gr.Markdown("### 📞 API Call Logs")
                logs_output = gr.Textbox(
                    label="API Logs",
                    lines=20,
                    max_lines=50,
                    interactive=False,
                    show_copy_button=True
                )
        
        # Full prompt section
        with gr.Row():
            prompt_output = gr.Textbox(
                label="📝 Full Prompt",
                lines=15,
                max_lines=30,
                interactive=False,
                show_copy_button=True
            )
        
        # Debug info section
        with gr.Row():
            debug_info = gr.Textbox(
                label="🐛 Debug Information",
                lines=5,
                interactive=False,
                show_copy_button=True
            )
        
        # Event handlers
        def init_and_update():
            result = initialize_app()
            choices = get_document_choices()
            debug = f"Initialization completed. Available documents: {len(documents_list)}"
            return result, choices, debug
        
        init_btn.click(
            fn=init_and_update,
            outputs=[init_status, document_dropdown, debug_info]
        )
        
        refresh_btn.click(
            fn=get_document_choices,
            outputs=document_dropdown
        )
        
        process_btn.click(
            fn=process_selected_document,
            inputs=document_dropdown,
            outputs=[result_output, logs_output]
        )
        
        show_prompt_btn.click(
            fn=show_full_prompt,
            inputs=document_dropdown,
            outputs=prompt_output
        )
        
        # Auto-initialize when app loads
        app.load(
            fn=init_and_update,
            outputs=[init_status, document_dropdown, debug_info]
        )
    
    return app

if __name__ == "__main__":
    # Create and launch the Gradio app
    app = create_gradio_interface()
    app.launch(
        server_name="0.0.0.0",
        server_port=7861,
        share=True,
        debug=True
    )
