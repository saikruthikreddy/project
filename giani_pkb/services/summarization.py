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

        if not self.gemini_api_key:
            raise ConfigurationError("Gemini API key must be provided.")

        initialize_gemini_client(self.gemini_api_key)

        try:
            self.model = genai.GenerativeModel(gemini_model)
        except Exception as e:
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
        self.logger.info(f"Starting chunk extraction for: {document_path}")
        
        if not os.path.isabs(document_path):
            document_path = os.path.join(os.getcwd(), document_path)

        if not os.path.exists(document_path):
            self.logger.error(f"Document not found: {document_path}")
            raise FileProcessingError(f"Document not found: {document_path}", filepath=document_path)

        try:
            parsed_blocks, _ = self.processor.process_single_file(document_path, "doc-id", "proj-id")
            
            if not parsed_blocks:
                self.logger.warning(f"No parsed blocks returned for: {document_path}")
                return []

            self.logger.info(f"Successfully extracted {len(parsed_blocks)} blocks")

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

            self.logger.info(f"Created {len(chunks)} chunks from document")
            return chunks
            
        except Exception as e:
            self.logger.error(f"Failed to process document content: {e}")
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
        self.logger.debug(f"Starting JSON cleanup, raw length: {len(raw)}")
        
        cleaned = raw.strip()
        
        # Extract content from code blocks
        if "```json" in cleaned:
            start = cleaned.find("```json") + 7
            end = cleaned.find("```", start)
            cleaned = cleaned[start:end].strip() if end != -1 else cleaned[start:].strip()
        elif "```" in cleaned:
            start = cleaned.find("```") + 3
            end = cleaned.find("```", start)
            cleaned = cleaned[start:end].strip() if end != -1 else cleaned[start:].strip()
        
        # Normalize brackets - find first { and last }
        if "{" in cleaned:
            cleaned = cleaned[cleaned.find("{"):]
        
        if "}" in cleaned:
            cleaned = cleaned[:cleaned.rfind("}") + 1]
        
        # Balance braces
        open_braces = cleaned.count("{")
        close_braces = cleaned.count("}")
        if open_braces > close_braces:
            cleaned += "}" * (open_braces - close_braces)
            self.logger.debug(f"Added {open_braces - close_braces} closing braces")
        
        # Fix common JSON errors
        cleaned = re.sub(r',\s*}', '}', cleaned)  # Remove trailing commas before }
        cleaned = re.sub(r',\s*]', ']', cleaned)  # Remove trailing commas before ]
        
        # Validate basic JSON structure
        is_valid = cleaned.startswith("{") and cleaned.endswith("}")
        if not is_valid:
            self.logger.warning("Invalid JSON structure after cleaning")
        
        return cleaned if is_valid else None

    def validate_llm_response(self, response: Dict[str, Any]) -> bool:
        """Validate LLM response structure."""
        self.logger.debug("Starting response validation")
        
        required_fields = {
            "ai_overall_key_themes_list": list,
            "ai_high_level_narrative_summary": list,
            "ai_main_topics_with_summaries_list_of_objects": list,
            "ai_key_takeaways_bullets": list,
            "extracted_metadata": dict,
            "extracted_keywords": list
        }

        for field, field_type in required_fields.items():
            if field not in response:
                self.logger.error(f"Missing field in response: {field}")
                return False
            if not isinstance(response[field], field_type):
                self.logger.error(f"Type mismatch for '{field}': expected {field_type}, got {type(response[field])}")
                return False

        self.logger.debug("All fields validated successfully")
        return True

    def call_llm_api(self, prompt: str, retries=3) -> Optional[Dict[str, Any]]:
        """Call LLM API with retries."""
        self.logger.info(f"Starting LLM API call with {retries} retries")
        
        for attempt in range(retries):
            try:
                self.logger.debug(f"LLM API attempt {attempt + 1}/{retries}")
                response = self.model.generate_content(prompt, generation_config=self.generation_config)
                
                if not response.text:
                    self.logger.error(f"Empty response from LLM on attempt {attempt + 1}")
                    raise APIError("Empty response from LLM")

                self.logger.debug(f"Received response, length: {len(response.text)}")

                try:
                    result = json.loads(response.text)
                    self.logger.debug("Direct JSON parse successful")
                    
                except json.JSONDecodeError as json_err:
                    self.logger.debug(f"Direct JSON parse failed: {json_err}")
                    
                    cleaned = self.extract_clean_json(response.text)
                    if not cleaned:
                        self.logger.error("Unable to clean JSON from LLM output")
                        raise ParsingError("Unable to clean and parse JSON from LLM output")
                    
                    try:
                        result = json.loads(cleaned)
                        self.logger.debug("Cleaned JSON parse successful")
                    except json.JSONDecodeError as clean_json_err:
                        self.logger.error(f"Even cleaned JSON failed to parse: {clean_json_err}")
                        raise ParsingError(f"JSON parsing failed even after cleaning: {clean_json_err}")

                result = self.normalize_keys(result)

                if self.validate_llm_response(result):
                    result["llm_used_for_processing"] = f"gemini-{self.model.model_name}"
                    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
                    self.api_call_tracker.log_api_call(prompt, str(result), self.model.model_name, timestamp)
                    self.logger.info("Successfully processed LLM response")
                    return result
                else:
                    self.logger.error(f"Response validation failed on attempt {attempt + 1}")
                    if attempt < retries - 1:
                        continue
                    else:
                        raise APIError("Response validation failed after all retries")

            except Exception as e:
                self.logger.error(f"LLM API attempt {attempt + 1} failed: {e}")
                if attempt < retries - 1:
                    sleep_time = 2 ** attempt
                    self.logger.info(f"Retrying in {sleep_time} seconds...")
                    time.sleep(sleep_time)
                else:
                    self.logger.error(f"All {retries} attempts failed")

        raise APIError("LLM API failed after retries")

    def summarize_document(self, document: DocumentMetadata) -> Optional[Dict[str, Any]]:
        """Summarize a single document."""
        self.logger.info(f"Starting summarization for: {document.originalFilename}")
        
        try:
            chunks = self.extract_document_chunks(document.storagePath)
            
            if not chunks:
                self.logger.warning("No chunks extracted from document")
                return None
                
            combined_text = "\n\n".join(chunk["text"] for chunk in chunks if chunk["text"])
            self.logger.debug(f"Combined text length: {len(combined_text)} characters")

            if not combined_text.strip():
                self.logger.warning("No text found in document chunks")
                return None

            try:
                prompt = get_appropriate_prompt(
                    document.finalCategory,
                    document.originalFilename,
                    document.finalCategory,
                    document.finalPurpose,
                    combined_text
                )
                self.logger.debug(f"Successfully generated prompt, length: {len(prompt)} characters")
                
            except Exception as prompt_error:
                self.logger.error(f"Failed to generate prompt: {prompt_error}")
                raise prompt_error

            llm_response = self.call_llm_api(prompt)
            
            if not llm_response:
                self.logger.error("No response from LLM API")
                return None

            self.logger.info("Received valid LLM response")

            result = {
                "document_id": document.id,
                "document_filename": document.originalFilename,
                "document_category": document.finalCategory,
                "source": document.source,
                "document_group": self.get_document_group(document.finalCategory).value,
                "user_note_purpose": document.finalPurpose,
                "processing_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                "llm_analysis": llm_response,
                "chunks_count": len(chunks)
            }

            summary_path = Path("data/summaries") / f"{document.id}_summary.json"
            self.logger.debug(f"Saving summary to: {summary_path}")
            
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            result["summaryStoragePath"] = str(summary_path)

            self.metadata_manager.update_document_metadata_entry(
                document.id, {"summaryStoragePath": str(summary_path)}
            )

            self.logger.info(f"Successfully summarized document: {document.originalFilename}")
            return result
            
        except Exception as exc:
            self.logger.error(f"Failed to summarize document {document.originalFilename}: {exc}")
            raise FileProcessingError(f"Failed to summarize document: {exc}", filepath=document.storagePath)

    def process_all_documents(self) -> List[Dict[str, Any]]:
        """Process all documents."""
        documents = self.metadata_manager.get_all_document_metadata()
        self.logger.info(f"Found {len(documents)} documents to process")
        
        results = []

        for i, doc in enumerate(documents):
            self.logger.info(f"Processing document {i+1}/{len(documents)}: {doc.originalFilename}")
            try:
                summary = self.summarize_document(doc)
                if summary:
                    results.append(summary)
                    self.logger.debug(f"Successfully processed document {i+1}")
                else:
                    self.logger.warning(f"No summary generated for document {i+1}")
            except Exception as e:
                self.logger.error(f"Error processing document {doc.originalFilename}: {e}")

        self.logger.info(f"Completed processing {len(results)} documents successfully")
        return results

    def save_summarization_results(self, results: List[Dict[str, Any]], output_report="data/all_summaries_report.json"):
        """Save summarization results to report file."""
        
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
            
            self.logger.info(f"Summarization report saved to: {output_report}")
            
        except Exception as e:
            self.logger.error(f"Error writing report file: {e}")
            raise FileProcessingError(f"Error writing report file: {e}", filepath=output_report)

    def get_api_call_summary(self) -> Dict[str, Any]:
        return self.api_call_tracker.get_summary()