import gradio as gr
import json
import os
import time
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum
import google.generativeai as genai
from pathlib import Path
from dotenv import load_dotenv
import tempfile

# Load environment variables
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
    TECHNICAL_SPECIFICATION = "19. Technical Specification Document"
    GENERIC_TEXT = "39. Generic Text Document"

class DocumentGroup(Enum):
    GROUP_A = "Strategic & Formal Client-Facing Deliverables/Inputs"
    GROUP_B = "Research, Analysis & Informational Inputs"
    GROUP_C = "Project Execution & Iterative Work Products"
    GROUP_D = "Conversational & Interaction Records"

class APICallTracker:
    def __init__(self):
        self.api_calls = []
        self.call_count = 0
    
    def log_api_call(self, prompt: str, response: str, model: str, timestamp: str):
        self.call_count += 1
        call_info = {
            "call_number": self.call_count,
            "timestamp": timestamp,
            "model": model,
            "prompt_preview": prompt[:200] + "..." if len(prompt) > 200 else prompt,
            "full_prompt": prompt,
            "response_preview": response[:200] + "..." if len(response) > 200 else response,
            "full_response": response,
            "prompt_length": len(prompt),
            "response_length": len(response)
        }
        self.api_calls.append(call_info)
        return call_info
    
    def get_summary(self):
        return {
            "total_calls": self.call_count,
            "total_prompt_chars": sum(call["prompt_length"] for call in self.api_calls),
            "total_response_chars": sum(call["response_length"] for call in self.api_calls),
            "calls": self.api_calls
        }

class GeminiDocumentProcessor:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv('GEMINI_API_KEY')
        if not self.api_key:
            raise ValueError("Gemini API key required")
        
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel("gemini-1.5-pro")
        self.tracker = APICallTracker()
        
        self.generation_config = genai.types.GenerationConfig(
            temperature=0.1,
            top_p=0.8,
            top_k=40,
            max_output_tokens=8192,
        )
    
    def extract_text_from_file(self, file_path: str) -> str:
        """Extract text content from uploaded file"""
        try:
            # Simple text extraction - you can enhance this with more sophisticated processors
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            return content[:10000]  # Limit to first 10k chars for demo
        except Exception as e:
            return f"Error reading file: {str(e)}"
    
    def get_group_a_prompt(self, filename: str, doc_type: str, purpose: str, content: str) -> str:
        """Generate Group A prompt for Strategic documents"""
        return f"""ROLE:
You are an AI Knowledge Analyst for Giani.ai, specializing in extracting critical information from consulting documents.

INPUT DOCUMENT DETAILS:
- Filename: '{filename}'
- Document Type: '{doc_type}'
- Purpose: '{purpose}'
- Content: '''{content}'''

YOUR TASK:
Analyze this document and extract:

1. **Key Themes** (3-5 main themes)
2. **Executive Summary** (2-3 paragraphs)
3. **Main Topics** with summaries
4. **Key Takeaways** (5 bullet points)
5. **Strategic Recommendations**

OUTPUT FORMAT (JSON):
{{
  "key_themes": ["theme1", "theme2", "theme3"],
  "executive_summary": "summary text",
  "main_topics": [
    {{"topic": "topic1", "summary": "summary1"}},
    {{"topic": "topic2", "summary": "summary2"}}
  ],
  "key_takeaways": ["takeaway1", "takeaway2", "takeaway3"],
  "recommendations": ["rec1", "rec2", "rec3"],
  "document_metadata": {{
    "title": "suggested title",
    "audience": "target audience",
    "sentiment": "document sentiment"
  }}
}}"""

    def call_gemini_api(self, prompt: str) -> Optional[str]:
        """Make API call to Gemini and track it"""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        
        try:
            print(f"\n🚀 Making Gemini API Call #{self.tracker.call_count + 1}")
            print(f"⏰ Timestamp: {timestamp}")
            print(f"📝 Prompt length: {len(prompt)} characters")
            print(f"🎯 Model: gemini-1.5-pro")
            
            response = self.model.generate_content(
                prompt,
                generation_config=self.generation_config
            )
            
            response_text = response.text if response.text else "No response generated"
            
            # Log the API call
            call_info = self.tracker.log_api_call(
                prompt=prompt,
                response=response_text,
                model="gemini-1.5-pro",
                timestamp=timestamp
            )
            
            print(f"✅ Response received: {len(response_text)} characters")
            print(f"📊 Total API calls so far: {self.tracker.call_count}")
            
            return response_text
            
        except Exception as e:
            error_msg = f"API Error: {str(e)}"
            self.tracker.log_api_call(
                prompt=prompt,
                response=error_msg,
                model="gemini-1.5-pro",
                timestamp=timestamp
            )
            print(f"❌ API call failed: {error_msg}")
            return error_msg
    
    def process_document(self, file_path: str, filename: str, doc_category: str, purpose: str) -> Dict[str, Any]:
        """Process a document and track all API calls"""
        print(f"\n🔄 Starting document processing for: {filename}")
        
        # Reset tracker for new document
        self.tracker = APICallTracker()
        
        # Extract content
        content = self.extract_text_from_file(file_path)
        print(f"📄 Extracted {len(content)} characters from document")
        
        # Generate prompt based on category
        prompt = self.get_group_a_prompt(filename, doc_category, purpose, content)
        
        # Make API call
        response = self.call_gemini_api(prompt)
        
        # Return results with API call tracking
        return {
            "processed_document": filename,
            "api_response": response,
            "api_call_summary": self.tracker.get_summary()
        }

def create_gradio_interface():
    """Create the Gradio interface"""
    
    # Initialize processor (will be created when API key is provided)
    processor = None
    
    def process_file_with_tracking(file, doc_category, purpose, api_key):
        nonlocal processor
        
        if not api_key:
            return "❌ Please provide a Gemini API key", "No API calls made", ""
        
        if not file:
            return "❌ Please upload a file", "No API calls made", ""
        
        try:
            # Initialize processor with API key
            processor = GeminiDocumentProcessor(api_key=api_key)
            
            # Process the document
            result = processor.process_document(
                file_path=file.name,
                filename=os.path.basename(file.name),
                doc_category=doc_category,
                purpose=purpose
            )
            
            # Format API calls for display
            api_summary = result["api_call_summary"]
            
            api_calls_display = f"""
# 📊 API Call Summary
- **Total Calls Made:** {api_summary['total_calls']}
- **Total Prompt Characters:** {api_summary['total_prompt_chars']:,}
- **Total Response Characters:** {api_summary['total_response_chars']:,}

## 🔍 Detailed API Calls:
"""
            
            for call in api_summary['calls']:
                api_calls_display += f"""
### Call #{call['call_number']} - {call['timestamp']}
**Model:** {call['model']}
**Prompt Length:** {call['prompt_length']:,} chars
**Response Length:** {call['response_length']:,} chars

**Prompt Preview:**
{call['prompt_preview']}

**Response Preview:**
{call['response_preview']}

"""
# Format the main response
            main_response = f"""
# 📋 Document Processing Results

**Document:** {result['processed_document']}

## 🤖 Gemini API Response:
{result['api_response']}
"""
            
            # Create detailed logs
            detailed_logs = ""
            for call in api_summary['calls']:
                detailed_logs += f"""
=== API CALL #{call['call_number']} ===
Timestamp: {call['timestamp']}
Model: {call['model']}

FULL PROMPT:
{call['full_prompt']}

FULL RESPONSE:
{call['full_response']}

{'='*80}
"""
            
            return main_response, api_calls_display, detailed_logs
            
        except Exception as e:
            error_msg = f"❌ Error processing file: {str(e)}"
            return error_msg, "Error occurred", str(e)
    
    # Create the interface
    with gr.Blocks(title="Gemini API Call Tracker", theme=gr.themes.Soft()) as demo:
        gr.Markdown("""
        # 🔍 Gemini API Call Tracker
        Upload a document and track all Gemini API calls made during processing.
        """)
        
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("## 📤 Input Configuration")
                
                api_key_input = gr.Textbox(
                    label="🔑 Gemini API Key",
                    placeholder="Enter your Gemini API key",
                    type="password"
                )
                
                file_input = gr.File(
                    label="📄 Upload Document",
                    file_types=[".txt", ".md", ".json", ".py", ".pdf"]
                )
                
                category_input = gr.Dropdown(
                    choices=[cat.value for cat in DocumentCategory],
                    label="📂 Document Category",
                    value=DocumentCategory.GENERIC_TEXT.value
                )
                
                purpose_input = gr.Textbox(
                    label="🎯 Document Purpose",
                    placeholder="Describe the purpose of this document",
                    value="General analysis and summarization"
                )
                
                process_btn = gr.Button("🚀 Process Document & Track API Calls", variant="primary")
        
        gr.Markdown("## 📊 Results")
        
        with gr.Tab("📋 Main Results"):
            main_output = gr.Markdown()
        
        with gr.Tab("📞 API Call Summary"):
            api_calls_output = gr.Markdown()
        
        with gr.Tab("🔍 Detailed Logs"):
            detailed_logs_output = gr.Textbox(
                label="Complete API Call Logs",
                lines=20,
                max_lines=50
            )
        
        # Connect the processing function
        process_btn.click(
            fn=process_file_with_tracking,
            inputs=[file_input, category_input, purpose_input, api_key_input],
            outputs=[main_output, api_calls_output, detailed_logs_output]
        )
        
        gr.Markdown("""
        ## 📝 Instructions:
        1. **Enter your Gemini API Key** (get one from [Google AI Studio](https://makersuite.google.com/app/apikey))
        2. **Upload a document** (text, markdown, JSON, Python files supported)
        3. **Select document category** and **enter purpose**
        4. **Click Process** to see all Gemini API calls in real-time
        
        The interface will show:
        - 📋 **Main Results**: Document analysis results
        - 📞 **API Call Summary**: Overview of all API calls made
        - 🔍 **Detailed Logs**: Complete request/response logs
        """)
    
    return demo

if __name__ == "__main__":
    # Create and launch the interface
    demo = create_gradio_interface()
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        debug=True
    )
