"""
Summarization service for processing and summarizing documents using Gemini LLM.
"""

import os
import time
import uuid
import json
import logging
import re
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import google.generativeai as genai

from models.document import DocumentMetadata
from services.metadata_manager import MetadataManagerService
from preprocessing.chunking.dto import ChunkDTO
from utils.constants import DocumentGroup, CATEGORY_TO_GROUP_MAPPING
from utils.exceptions import APIError, FileProcessingError, ParsingError, ConfigurationError
from utils.config import GEMINI_API_KEY, GEMINI_PRO_MODEL
from preprocessing.document_processor import DocumentProcessor
from utils.gemini_client import initialize_gemini_client
from utils.api_tracker import APICallTracker
from utils.prompt_generators import get_both_prompts, get_summarization_prompt, get_metadata_prompt

class SummarizationService:
    """
    Service for summarizing documents using Gemini LLM with parallel summarization and metadata extraction.
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

        # Gemini Generation Config for JSON response
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
        # TODO: Update this method to use blob storage
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
        """Clean malformed JSON content with improved handling of extra data."""
        self.logger.debug(f"Starting JSON cleanup, raw length: {len(raw)}")

        self.logger.info(raw)
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

        # Find the main JSON object - look for balanced braces
        if "{" in cleaned:
            start_pos = cleaned.find("{")
            brace_count = 0
            end_pos = start_pos

            for i, char in enumerate(cleaned[start_pos:], start_pos):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        end_pos = i + 1
                        break

            # Extract only the balanced JSON object
            cleaned = cleaned[start_pos:end_pos]
            self.logger.debug(f"Extracted balanced JSON from position {start_pos} to {end_pos}")

        # Fix common JSON errors
        cleaned = re.sub(r',\s*}', '}', cleaned)  # Remove trailing commas before }
        cleaned = re.sub(r',\s*]', ']', cleaned)  # Remove trailing commas before ]

        # Remove any remaining extra characters after the JSON
        cleaned = cleaned.strip()

        # Validate basic JSON structure
        is_valid = cleaned.startswith("{") and cleaned.endswith("}")
        if not is_valid:
            self.logger.warning("Invalid JSON structure after cleaning")
            return None

        # Try to parse to ensure it's valid JSON
        try:
            json.loads(cleaned)
            self.logger.debug("JSON validation successful")
            return cleaned
        except json.JSONDecodeError as e:
            self.logger.warning(f"JSON still invalid after cleaning: {e}")
            return None

    def validate_summarization_response(self, response: Dict[str, Any]) -> bool:
        """Validate summarization response structure."""
        self.logger.debug("Validating summarization response")

        required_fields = {
            "ai_overall_key_themes_list": list,
            "ai_high_level_narrative_summary": list,
            "ai_main_topics_with_summaries_list_of_objects": list,
            "ai_key_takeaways_bullets": list,
            # "ai_tldr_key_finding": str
        }

        for field, field_type in required_fields.items():
            if field not in response:
                self.logger.error(f"Missing field in summarization response: {field}")
                return False
            if not isinstance(response[field], field_type):
                self.logger.error(f"Type mismatch for '{field}': expected {field_type}, got {type(response[field])}")
                return False

        # Validate structure of main topics
        for topic in response["ai_main_topics_with_summaries_list_of_objects"]:
            if not isinstance(topic, dict) or "topic_name" not in topic or "topic_summary" not in topic:
                self.logger.error("Invalid structure in ai_main_topics_with_summaries_list_of_objects")
                return False

        self.logger.debug("Summarization response validated successfully")
        return True

    def validate_metadata_response(self, response: Dict[str, Any]) -> bool:
        """Validate metadata response structure."""
        self.logger.debug("Validating metadata response")

        required_fields = {
            "extracted_metadata": dict,
            "extracted_keywords": list,
            "llm_used_for_processing": str
        }

        for field, field_type in required_fields.items():
            if field not in response:
                self.logger.error(f"Missing required field in metadata response: {field}")
                return False
            if not isinstance(response[field], field_type):
                self.logger.error(f"Type mismatch for '{field}': expected {field_type}, got {type(response[field])}")
                return False

        # Validate extracted_metadata structure
        metadata = response["extracted_metadata"]
        required_metadata_sections = ["intelligence_layer", "rag_specific_metadata", "universal_metadata"]

        for section in required_metadata_sections:
            if section not in metadata:
                self.logger.error(f"Missing section in extracted_metadata: {section}")
                return False

        # Validate intelligence_layer structure
        intelligence_layer = metadata["intelligence_layer"]
        required_intel_fields = ["strategy_and_objectives", "key_findings_and_data", "risks_and_mitigations", "execution_and_actions"]

        for field in required_intel_fields:
            if field not in intelligence_layer:
                self.logger.error(f"Missing field in intelligence_layer: {field}")
                return False
            if not isinstance(intelligence_layer[field], list):
                self.logger.error(f"Field '{field}' in intelligence_layer should be a list")
                return False

        self.logger.debug("Metadata response validated successfully")
        return True

    def call_llm_api(self, prompt: str, prompt_type: str, retries: int = 3) -> Optional[Dict[str, Any]]:
        """Call LLM API with retries for either summarization or metadata extraction."""
        self.logger.info(f"Starting {prompt_type} LLM API call with {retries} retries")

        for attempt in range(retries):
            try:
                self.logger.debug(f"{prompt_type} LLM API attempt {attempt + 1}/{retries}")
                response = self.model.generate_content(prompt, generation_config=self.generation_config)

                if not response.text:
                    self.logger.error(f"Empty response from LLM on attempt {attempt + 1}")
                    raise APIError("Empty response from LLM")

                self.logger.debug(f"Received {prompt_type} response, length: {len(response.text)}")

                try:
                    result = json.loads(response.text)
                    self.logger.debug(f"Direct JSON parse successful for {prompt_type}")

                except json.JSONDecodeError as json_err:
                    self.logger.debug(f"Direct JSON parse failed for {prompt_type}: {json_err}")

                    cleaned = self.extract_clean_json(response.text)
                    if not cleaned:
                        self.logger.error(f"Unable to clean JSON from {prompt_type} LLM output")
                        raise ParsingError(f"Unable to clean and parse JSON from {prompt_type} LLM output")

                    try:
                        result = json.loads(cleaned)
                        self.logger.debug(f"Cleaned JSON parse successful for {prompt_type}")
                    except json.JSONDecodeError as clean_json_err:
                        self.logger.error(f"Even cleaned JSON failed to parse for {prompt_type}: {clean_json_err}")
                        raise ParsingError(f"JSON parsing failed even after cleaning for {prompt_type}: {clean_json_err}")

                result = self.normalize_keys(result)

                # Validate based on prompt type
                is_valid = False
                if prompt_type == "summarization":
                    is_valid = self.validate_summarization_response(result)
                elif prompt_type == "metadata":
                    is_valid = self.validate_metadata_response(result)

                if is_valid:
                    if prompt_type == "metadata" and "llm_used_for_processing" not in result:
                        result["llm_used_for_processing"] = f"gemini-{self.model.model_name}"

                    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
                    self.api_call_tracker.log_api_call(prompt, str(result), self.model.model_name, timestamp)
                    self.logger.info(f"Successfully processed {prompt_type} LLM response")
                    return result
                else:
                    self.logger.error(f"{prompt_type} response validation failed on attempt {attempt + 1}")
                    if attempt < retries - 1:
                        continue
                    else:
                        raise APIError(f"{prompt_type} response validation failed after all retries")

            except Exception as e:
                self.logger.error(f"{prompt_type} LLM API attempt {attempt + 1} failed: {e}")
                if attempt < retries - 1:
                    sleep_time = 2 ** attempt
                    self.logger.info(f"Retrying in {sleep_time} seconds...")
                    time.sleep(sleep_time)
                else:
                    self.logger.error(f"All {retries} attempts failed for {prompt_type}")

        raise APIError(f"{prompt_type} LLM API failed after retries")

    def call_llm_apis_parallel(self, document_category: str, document_filename: str, user_purpose: str, combined_text: str) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], float, float]:
        """Call both summarization and metadata LLM APIs in parallel and return individual durations."""
        self.logger.info(f"Starting parallel LLM API calls for category: {document_category}")

        try:
            # Get both prompts using the existing prompt generators
            summarization_prompt, metadata_prompt = get_both_prompts(
                document_category,
                document_filename,
                document_category,  # Using category as documentSourceType
                user_purpose,
                combined_text
            )
            self.logger.debug("Successfully generated both prompts")
        except Exception as e:
            self.logger.error(f"Failed to generate prompts: {e}")
            raise e

        summarization_result = None
        metadata_result = None
        summarization_duration = 0
        metadata_duration = 0

        # Use ThreadPoolExecutor for parallel execution
        with ThreadPoolExecutor(max_workers=2) as executor:
            # Submit both tasks with timing
            summarization_start = time.time()
            future_summarization = executor.submit(self.call_llm_api, summarization_prompt, "summarization")

            metadata_start = time.time()
            future_metadata = executor.submit(self.call_llm_api, metadata_prompt, "metadata")

            # Collect results as they complete
            for future in as_completed([future_summarization, future_metadata]):
                try:
                    if future == future_summarization:
                        summarization_result = future.result()
                        summarization_duration = time.time() - summarization_start
                        self.logger.info(f"Summarization API call completed in {summarization_duration:.2f}s")
                    elif future == future_metadata:
                        metadata_result = future.result()
                        metadata_duration = time.time() - metadata_start
                        self.logger.info(f"Metadata API call completed in {metadata_duration:.2f}s")
                except Exception as e:
                    if future == future_summarization:
                        self.logger.error(f"Summarization API call failed: {e}")
                        summarization_duration = time.time() - summarization_start
                    elif future == future_metadata:
                        self.logger.error(f"Metadata API call failed: {e}")
                        metadata_duration = time.time() - metadata_start

        return summarization_result, metadata_result, summarization_duration, metadata_duration

    def summarize_from_chunk_dtos(self, document: DocumentMetadata, chunk_dtos: List[ChunkDTO]) -> Optional[Dict[str, Any]]:
        """
        Summarize a document using ChunkDTO objects with parallel processing.
        This method runs both summarization and metadata extraction in parallel.
        Args:
            document: DocumentMetadata object containing document information
            chunk_dtos: List of ChunkDTO objects from the chunking process
        Returns:
            Dictionary containing both summarization and metadata results or None if failed
        """
        self.logger.info(f"Starting parallel summarization from ChunkDTO objects for: {document.originalFilename}")
        start_time = time.time()

        try:
            if not chunk_dtos:
                self.logger.warning("No ChunkDTO objects provided for summarization")
                return None

            self.logger.debug(f"Processing {len(chunk_dtos)} ChunkDTO objects")

            # Extract text from ChunkDTO objects
            combined_text = "\n\n".join(
                chunk_dto.chunk_text for chunk_dto in chunk_dtos if chunk_dto.chunk_text.strip()
            )
            self.logger.debug(f"Combined text from {len(chunk_dtos)} chunks, length: {len(combined_text)} characters")

            if not combined_text.strip():
                self.logger.warning("No text found in provided ChunkDTO objects")
                return None

            # Call both APIs in parallel and get individual durations
            summarization_result, metadata_result, summarization_duration, metadata_duration = self.call_llm_apis_parallel(
                document.finalCategory,
                document.originalFilename,
                document.finalPurpose,
                combined_text
            )

            if not summarization_result or not metadata_result:
                self.logger.error("One or both LLM API calls failed")
                return None

            self.logger.info("Both LLM API calls completed successfully")

            # Prepare final result with proper duration tracking
            total_duration = time.time() - start_time
            result = {
                "document_id": document.id,
                "document_filename": document.originalFilename,
                "document_category": document.finalCategory,
                "source": document.source,
                "document_group": self.get_document_group(document.finalCategory).value,
                "user_note_purpose": document.finalPurpose,
                "processing_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                "summarization_analysis": summarization_result,
                "metadata_analysis": metadata_result,
                "chunks_count": len(chunk_dtos),
                "processing_method": "from_chunk_dtos_parallel",
                "processing_duration_seconds": total_duration,
                "summarization_duration_seconds": summarization_duration,
                "metadata_duration_seconds": metadata_duration
            }

            self.logger.info(f"Successfully completed parallel summarization for: {document.originalFilename}")
            return result

        except Exception as exc:
            self.logger.error(f"Failed to summarize document from ChunkDTO objects {document.originalFilename}: {exc}")
            raise FileProcessingError(f"Failed to summarize document from ChunkDTO objects: {exc}", filepath=document.storagePath)

    def summarize_document(self, document: DocumentMetadata) -> Optional[Dict[str, Any]]:
        """
        Summarize a single document by processing the file directly with parallel processing.
        This method is kept for backward compatibility and standalone usage.
        """
        self.logger.info(f"Starting file-based parallel summarization for: {document.originalFilename}")

        try:
            chunks = self.extract_document_chunks(document.storagePath)

            if not chunks:
                self.logger.warning("No chunks extracted from document")
                return None

            return self.summarize_from_chunks(document, chunks)

        except Exception as exc:
            self.logger.error(f"Failed to summarize document {document.originalFilename}: {exc}")
            raise FileProcessingError(f"Failed to summarize document: {exc}", filepath=document.storagePath)

    def process_all_documents(self) -> List[Dict[str, Any]]:
        """Process all documents with parallel summarization and metadata extraction."""
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

    def get_api_call_summary(self) -> Dict[str, Any]:
        return self.api_call_tracker.get_summary()
