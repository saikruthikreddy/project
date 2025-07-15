"""
Summarization service for processing and summarizing documents using Gemini LLM.
"""

import os
import time
import uuid
import json
import logging
import re
from typing import Dict, List, Any, Optional
from pathlib import Path

import google.generativeai as genai

from giani_pkb.models.document import DocumentMetadata
from giani_pkb.services.metadata_manager import MetadataManagerService
from giani_pkb.utils.constants import DocumentGroup, CATEGORY_TO_GROUP_MAPPING
from giani_pkb.utils.exceptions import APIError, FileProcessingError, ParsingError, ConfigurationError
from giani_pkb.utils.config import GEMINI_API_KEY, GEMINI_PRO_MODEL
from giani_pkb.preprocessing.document_processor import DocumentProcessor
from giani_pkb.utils.gemini_client import initialize_gemini_client
from giani_pkb.utils.api_tracker import APICallTracker
from giani_pkb.utils.prompt_generators import get_appropriate_prompt


class SummarizationService:
    """
    Service for summarizing documents using Gemini LLM based on document categories.
    """

    def __init__(self,
                 master_metadata_path: Optional[str] = None,
                 gemini_api_key: Optional[str] = None,
                 gemini_model: str = GEMINI_PRO_MODEL):
        self.logger = logging.getLogger(__name__)
        self.metadata_manager = MetadataManagerService(master_metadata_path=master_metadata_path)
        self.gemini_api_key = gemini_api_key or GEMINI_API_KEY

        print(f"[INIT] Initializing SummarizationService with model: {gemini_model}", flush=True)

        if not self.gemini_api_key:
            raise ConfigurationError("Gemini API key must be provided.")

        initialize_gemini_client(self.gemini_api_key)

        try:
            self.model = genai.GenerativeModel(gemini_model)
            print(f"[INIT] Successfully initialized Gemini model: {gemini_model}", flush=True)
        except Exception as e:
            print(f"[INIT ERROR] Failed to initialize Gemini model: {e}", flush=True)
            raise ConfigurationError(f"Failed to initialize Gemini model: {e}")

        self.processor = DocumentProcessor(api_keys={'gemini': self.gemini_api_key})
        self.api_call_tracker = APICallTracker()
        Path("data/summaries").mkdir(parents=True, exist_ok=True)

        # Gemini Generation Config with JSON schema
        self.generation_config = genai.types.GenerationConfig(
            temperature=0.1,
            top_p=0.8,
            top_k=40,
            max_output_tokens=8192,
            response_mime_type="application/json",
        )

    def get_document_group(self, category: str) -> DocumentGroup:
        return CATEGORY_TO_GROUP_MAPPING.get(category, DocumentGroup.GROUP_D)

    def extract_document_chunks(self, document_path: str) -> List[Dict[str, Any]]:
        """Extracts text chunks from a document."""
        print(f"[EXTRACT] Starting chunk extraction for: {document_path}", flush=True)
        
        if not os.path.isabs(document_path):
            document_path = os.path.join(os.getcwd(), document_path)

        if not os.path.exists(document_path):
            print(f"[EXTRACT ERROR] Document not found: {document_path}", flush=True)
            raise FileProcessingError(f"Document not found: {document_path}", filepath=document_path)

        try:
            print(f"[EXTRACT] Processing file with DocumentProcessor...", flush=True)
            parsed_blocks, _ = self.processor.process_single_file(document_path, "doc-id", "proj-id")
            
            if not parsed_blocks:
                print(f"[EXTRACT WARNING] No parsed blocks returned for: {document_path}", flush=True)
                return []

            print(f"[EXTRACT] Successfully extracted {len(parsed_blocks)} blocks", flush=True)

            chunks = []
            for i, block in enumerate(parsed_blocks):
                text = block[0] if isinstance(block, tuple) and len(block) > 0 else ""
                meta = block[1] if isinstance(block, tuple) and len(block) > 1 else {}
                chunks.append({
                    "text": text,
                    "metadata": meta,
                    "chunk_id": str(uuid.uuid4()),
                    "chunk_index": i,
                    "vector_id": block[2] if len(block) > 2 else None,
                    "embedding_checksum": block[3] if len(block) > 3 else None
                })

            print(f"[EXTRACT] Created {len(chunks)} chunks from document", flush=True)
            return chunks
            
        except Exception as e:
            print(f"[EXTRACT ERROR] Failed to process document content: {e}", flush=True)
            print(f"[EXTRACT ERROR] Error type: {type(e).__name__}", flush=True)
            raise ParsingError(f"Failed to process document content: {e}", filename=document_path)

    def normalize_keys(self, d):
        """Strip whitespace from all JSON keys recursively."""
        if isinstance(d, dict):
            return {k.strip(): self.normalize_keys(v) for k, v in d.items()}
        elif isinstance(d, list):
            return [self.normalize_keys(i) for i in d]
        return d


    def extract_clean_json(self, raw: str) -> Optional[str]:
        """Clean malformed JSON content."""
        print(f"[JSON CLEAN] Starting JSON cleanup, raw length: {len(raw)}", flush=True)
        print(f"[JSON CLEAN] First 200 chars of raw response: {repr(raw[:200])}", flush=True)
        
        cleaned = raw.strip()
        
        # Extract content from code blocks
        if "```json" in cleaned:
            start = cleaned.find("```json") + 7
            end = cleaned.find("```", start)
            cleaned = cleaned[start:end].strip() if end != -1 else cleaned[start:].strip()
            print(f"[JSON CLEAN] Found ```json markers, extracted content", flush=True)
        elif "```" in cleaned:
            start = cleaned.find("```") + 3
            end = cleaned.find("```", start)
            cleaned = cleaned[start:end].strip() if end != -1 else cleaned[start:].strip()
            print(f"[JSON CLEAN] Found ``` markers, extracted content", flush=True)
        
        # Normalize brackets - find first { and last }
        if "{" in cleaned:
            cleaned = cleaned[cleaned.find("{"):]
            print(f"[JSON CLEAN] Trimmed to first {{", flush=True)
        
        if "}" in cleaned:
            cleaned = cleaned[:cleaned.rfind("}") + 1]
            print(f"[JSON CLEAN] Trimmed to last }}", flush=True)
        
        # Balance braces
        open_braces = cleaned.count("{")
        close_braces = cleaned.count("}")
        if open_braces > close_braces:
            cleaned += "}" * (open_braces - close_braces)
            print(f"[JSON CLEAN] Added {open_braces - close_braces} closing braces", flush=True)
        
        # Fix common JSON errors
        cleaned = re.sub(r',\s*}', '}', cleaned)  # Remove trailing commas before }
        cleaned = re.sub(r',\s*]', ']', cleaned)  # Remove trailing commas before ]
        
        print(f"[JSON CLEAN] Final cleaned length: {len(cleaned)}", flush=True)
        print(f"[JSON CLEAN] First 200 chars of cleaned: {repr(cleaned[:200])}", flush=True)
        print(f"[JSON CLEAN] Last 200 chars of cleaned: {repr(cleaned[-200:])}", flush=True)
        
        # Validate basic JSON structure
        is_valid = cleaned.startswith("{") and cleaned.endswith("}")
        print(f"[JSON CLEAN] Is valid JSON structure: {is_valid}", flush=True)
        
        return cleaned if is_valid else None

    def validate_llm_response(self, response: Dict[str, Any]) -> bool:
        """Validate LLM response structure."""
        print(f"[VALIDATE] Starting response validation", flush=True)
        print(f"[VALIDATE] Response keys: {list(response.keys())}", flush=True)
        
        required_fields = {
            "ai_overall_key_themes_list": list,
            "ai_high_level_narrative_summary": str,
            "ai_main_topics_with_summaries_list_of_objects": list,
            "ai_key_takeaways_bullets": list,
            "extracted_metadata": dict,
            "extracted_keywords": list
        }

        for field, field_type in required_fields.items():
            if field not in response:
                print(f"[VALIDATE ERROR] Missing field in response: {field}", flush=True)
                return False
            if not isinstance(response[field], field_type):
                print(f"[VALIDATE ERROR] Type mismatch for '{field}': expected {field_type}, got {type(response[field])}", flush=True)
                return False
            print(f"[VALIDATE] ✓ Field '{field}' is valid ({field_type.__name__})", flush=True)

        print(f"[VALIDATE] ✓ All fields validated successfully", flush=True)
        return True

    def call_llm_api(self, prompt: str, retries=3) -> Optional[Dict[str, Any]]:
        """Call LLM API with retries."""
        print(f"[LLM API] Starting LLM API call with {retries} retries", flush=True)
        print(f"[LLM API] Prompt length: {len(prompt)} characters", flush=True)
        
        for attempt in range(retries):
            print(f"[LLM API] Attempt {attempt + 1}/{retries}", flush=True)
            
            try:
                print(f"[LLM API] Sending request to Gemini...", flush=True)
                response = self.model.generate_content(prompt, generation_config=self.generation_config)
                
                if not response.text:
                    print(f"[LLM API ERROR] Empty response from LLM on attempt {attempt + 1}", flush=True)
                    raise APIError("Empty response from LLM")

                print(f"[LLM API] Received response, length: {len(response.text)}", flush=True)
                print(f"[LLM API] Raw response preview (first 300 chars): {repr(response.text[:300])}", flush=True)

                try:
                    print(f"[LLM API] Attempting direct JSON parse...", flush=True)
                    result = json.loads(response.text)
                    print(f"[LLM API] ✓ Direct JSON parse successful", flush=True)
                    
                except json.JSONDecodeError as json_err:
                    print(f"[LLM API] Direct JSON parse failed: {json_err}", flush=True)
                    print(f"[LLM API] Attempting to clean JSON...", flush=True)
                    
                    cleaned = self.extract_clean_json(response.text)
                    if not cleaned:
                        print(f"[LLM API ERROR] Unable to clean JSON from LLM output", flush=True)
                        raise ParsingError("Unable to clean and parse JSON from LLM output")
                    
                    try:
                        result = json.loads(cleaned)
                        print(f"[LLM API] ✓ Cleaned JSON parse successful", flush=True)
                    except json.JSONDecodeError as clean_json_err:
                        print(f"[LLM API ERROR] Even cleaned JSON failed to parse: {clean_json_err}", flush=True)
                        raise ParsingError(f"JSON parsing failed even after cleaning: {clean_json_err}")

                print(f"[LLM API] Normalizing keys...", flush=True)
                result = self.normalize_keys(result)

                print(f"[LLM API] Validating response structure...", flush=True)
                if self.validate_llm_response(result):
                    result["llm_used_for_processing"] = f"gemini-{self.model.model_name}"
                    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
                    self.api_call_tracker.log_api_call(prompt, str(result), self.model.model_name, timestamp)
                    print(f"[LLM API] ✓ Successfully processed LLM response", flush=True)
                    return result
                else:
                    print(f"[LLM API ERROR] Response validation failed on attempt {attempt + 1}", flush=True)
                    if attempt < retries - 1:
                        continue
                    else:
                        raise APIError("Response validation failed after all retries")

            except Exception as e:
                print(f"[LLM API ERROR] Attempt {attempt + 1} failed: {e}", flush=True)
                print(f"[LLM API ERROR] Error type: {type(e).__name__}", flush=True)
                if attempt < retries - 1:
                    sleep_time = 2 ** attempt
                    print(f"[LLM API] Retrying in {sleep_time} seconds...", flush=True)
                    time.sleep(sleep_time)
                else:
                    print(f"[LLM API ERROR] All {retries} attempts failed", flush=True)

        raise APIError("LLM API failed after retries")

    def summarize_document(self, document: DocumentMetadata) -> Optional[Dict[str, Any]]:
        """Summarize a single document."""
        print(f"[SUMMARIZE] Starting summarization for: {document.originalFilename}", flush=True)
        print(f"[SUMMARIZE] Document ID: {document.id}", flush=True)
        print(f"[SUMMARIZE] Document category: {document.finalCategory}", flush=True)
        print(f"[SUMMARIZE] Document purpose: {document.finalPurpose}", flush=True)
        print(f"[SUMMARIZE] Storage path: {document.storagePath}", flush=True)
        
        try:
            print(f"[SUMMARIZE] Extracting document chunks...", flush=True)
            chunks = self.extract_document_chunks(document.storagePath)
            
            if not chunks:
                print(f"[SUMMARIZE WARNING] No chunks extracted from document", flush=True)
                return None
                
            combined_text = "\n\n".join(chunk["text"] for chunk in chunks if chunk["text"])
            print(f"[SUMMARIZE] Combined text length: {len(combined_text)} characters", flush=True)

            if not combined_text.strip():
                print(f"[SUMMARIZE WARNING] No text found in document chunks.", flush=True)
                return None

            print(f"[SUMMARIZE] Generating prompt for category: {document.finalCategory}", flush=True)
            
            # Add debugging around prompt generation
            try:
                print(f"[PROMPT] Calling get_appropriate_prompt with:", flush=True)
                print(f"[PROMPT]   - category: {repr(document.finalCategory)}", flush=True)
                print(f"[PROMPT]   - filename: {repr(document.originalFilename)}", flush=True)
                print(f"[PROMPT]   - purpose: {repr(document.finalPurpose)}", flush=True)
                print(f"[PROMPT]   - text_length: {len(combined_text)}", flush=True)
                
                # Import the function to inspect it
                from giani_pkb.utils.prompt_generators import get_appropriate_prompt
                print(f"[PROMPT] Function imported successfully", flush=True)
                
                # Check if there are any module-level variables that might have the bad key
                import giani_pkb.utils.prompt_generators as prompt_module
                print(f"[PROMPT] Module attributes: {dir(prompt_module)}", flush=True)
                
                prompt = get_appropriate_prompt(
                    document.finalCategory,
                    document.originalFilename,
                    document.finalCategory,
                    document.finalPurpose,
                    combined_text
                )
                print(f"[PROMPT] ✓ Successfully generated prompt, length: {len(prompt)} characters", flush=True)
                
            except Exception as prompt_error:
                print(f"[PROMPT ERROR] Failed to generate prompt: {prompt_error}", flush=True)
                print(f"[PROMPT ERROR] Error type: {type(prompt_error).__name__}", flush=True)
                print(f"[PROMPT ERROR] Full error details: {repr(prompt_error)}", flush=True)
                
                # Let's also inspect what might be causing this
                try:
                    import giani_pkb.utils.prompt_generators as prompt_module
                    for attr_name in dir(prompt_module):
                        if not attr_name.startswith('_'):
                            attr_value = getattr(prompt_module, attr_name)
                            if isinstance(attr_value, dict):
                                print(f"[PROMPT DEBUG] Found dict attribute '{attr_name}' with keys:", flush=True)
                                for key in attr_value.keys():
                                    print(f"[PROMPT DEBUG]   Key: {repr(key)}", flush=True)
                                    if '\n' in str(key) or '  ' in str(key):
                                        print(f"[PROMPT DEBUG]   ⚠ BAD KEY FOUND: {repr(key)}", flush=True)
                except Exception as debug_error:
                    print(f"[PROMPT DEBUG ERROR] Could not inspect module: {debug_error}", flush=True)
                
                raise prompt_error

            print(f"[SUMMARIZE] Calling LLM API...", flush=True)
            llm_response = self.call_llm_api(prompt)
            
            if not llm_response:
                print(f"[SUMMARIZE ERROR] No response from LLM API", flush=True)
                return None

            print(f"[SUMMARIZE] ✓ Received valid LLM response", flush=True)

            result = {
                "document_id": document.id,
                "document_filename": document.originalFilename,
                "document_category": document.finalCategory,
                "document_group": self.get_document_group(document.finalCategory).value,
                "user_note_purpose": document.finalPurpose,
                "processing_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                "llm_analysis": llm_response,
                "chunks_count": len(chunks)
            }

            summary_path = Path("data/summaries") / f"{document.id}_summary.json"
            print(f"[SUMMARIZE] Saving summary to: {summary_path}", flush=True)
            
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            result["summaryStoragePath"] = str(summary_path)

            print(f"[SUMMARIZE] Updating metadata manager...", flush=True)
            self.metadata_manager.update_document_metadata_entry(
                document.id, {"summaryStoragePath": str(summary_path)}
            )

            print(f"[SUMMARIZE] ✓ Successfully summarized document: {document.originalFilename}", flush=True)
            return result
            
        except Exception as exc:
            print(f"[SUMMARIZE ERROR] Failed to summarize document {document.originalFilename}: {exc}", flush=True)
            print(f"[SUMMARIZE ERROR] Error type: {type(exc).__name__}", flush=True)
            print(f"[SUMMARIZE ERROR] Full error details: {repr(exc)}", flush=True)
            raise FileProcessingError(f"Failed to summarize document: {exc}", filepath=document.storagePath)

    def process_all_documents(self) -> List[Dict[str, Any]]:
        """Process all documents."""
        print(f"[PROCESS ALL] Starting processing of all documents", flush=True)
        documents = self.metadata_manager.get_all_document_metadata()
        print(f"[PROCESS ALL] Found {len(documents)} documents to process", flush=True)
        
        results = []

        for i, doc in enumerate(documents):
            print(f"[PROCESS ALL] Processing document {i+1}/{len(documents)}: {doc.originalFilename}", flush=True)
            try:
                summary = self.summarize_document(doc)
                if summary:
                    results.append(summary)
                    print(f"[PROCESS ALL] ✓ Successfully processed document {i+1}", flush=True)
                else:
                    print(f"[PROCESS ALL] ⚠ No summary generated for document {i+1}", flush=True)
            except Exception as e:
                print(f"[PROCESS ALL ERROR] Error processing document {doc.originalFilename}: {e}", flush=True)
                print(f"[PROCESS ALL ERROR] Error type: {type(e).__name__}", flush=True)

        print(f"[PROCESS ALL] ✓ Completed processing. {len(results)} successful summaries", flush=True)
        return results

    def save_summarization_results(self, results: List[Dict[str, Any]], output_report="data/all_summaries_report.json"):
        """Save summarization results to report file."""
        print(f"[SAVE RESULTS] Saving summarization results to: {output_report}", flush=True)
        
        try:
            report_data = {
                "report_metadata": {
                    "total_documents_processed": len(results),
                    "total_summaries_successfully_saved": sum(1 for r in results if r.get("summaryStoragePath")),
                    "processing_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                    "version": "1.1"
                },
                "individual_summary_paths": [r["summaryStoragePath"] for r in results if r.get("summaryStoragePath")],
                "api_call_summary": self.get_api_call_summary()
            }

            Path(output_report).parent.mkdir(parents=True, exist_ok=True)
            with open(output_report, "w", encoding="utf-8") as f:
                json.dump(report_data, f, indent=2, ensure_ascii=False)
            print(f"[SAVE RESULTS] ✓ Summarization report saved successfully", flush=True)
            
        except Exception as e:
            print(f"[SAVE RESULTS ERROR] Error writing report file: {e}", flush=True)
            raise FileProcessingError(f"Error writing report file: {e}", filepath=output_report)

    def get_api_call_summary(self) -> Dict[str, Any]:
        return self.api_call_tracker.get_summary()
