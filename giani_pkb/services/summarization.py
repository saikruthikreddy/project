"""
Summarization service for processing and summarizing documents using Gemini LLM.
"""
import json
import os
import logging
import time
from typing import Dict, List, Any, Optional
from pathlib import Path

import google.generativeai as genai

from giani_pkb.models.document import DocumentMetadata
from giani_pkb.services.metadata_manager import MetadataManagerService
from giani_pkb.utils.exceptions import APIError, FileProcessingError, ParsingError, ConfigurationError
from giani_pkb.utils.constants import DocumentGroup, CATEGORY_TO_GROUP_MAPPING
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
        """
        Initialize the SummarizationService.

        Args:
            master_metadata_path: Optional path to master metadata file
            gemini_api_key: Optional custom API key
            gemini_model: Gemini model to use for summarization
        """
        self.logger = logging.getLogger(__name__)
        self.metadata_manager = MetadataManagerService(master_metadata_path=master_metadata_path)
        self.gemini_model = gemini_model

        current_api_key = gemini_api_key if gemini_api_key else GEMINI_API_KEY
        if not current_api_key:
            self.logger.error("Gemini API key must be provided for SummarizationService.")
            raise ConfigurationError("Gemini API key must be provided either as parameter or via GEMINI_API_KEY in config/env")

        # Initialize Gemini client with the appropriate API key
        initialize_gemini_client(current_api_key)

        try:
            self.model = genai.GenerativeModel(self.gemini_model)
        except Exception as e:
            self.logger.error(f"Failed to initialize GenerativeModel with {self.gemini_model}. Error: {type(e).__name__} - {e}")
            raise ConfigurationError(f"Failed to initialize GenerativeModel with {self.gemini_model}. Please check model name and API key configuration. Original error: {e}")

        self.generation_config = genai.types.GenerationConfig(
            temperature=0.1,
            top_p=0.8,
            top_k=40,
            max_output_tokens=8192,
        )

        self.processor = DocumentProcessor(api_key=current_api_key)
        self.api_call_tracker = APICallTracker()

        Path("data/summaries").mkdir(parents=True, exist_ok=True)
        self.logger.info("SummarizationService initialized. Summary directory 'data/summaries' ensured.")

    def get_document_group(self, category: str) -> DocumentGroup:
        """Determine which group a document belongs to based on its category."""
        return CATEGORY_TO_GROUP_MAPPING.get(category, DocumentGroup.GROUP_D)

    def extract_document_chunks(self, document_path: str) -> str:
        """Extract key document content chunks from the document file."""
        try:
            if not os.path.isabs(document_path):
                full_path = os.path.join(os.getcwd(), document_path)
            else:
                full_path = document_path

            if not os.path.exists(full_path):
                self.logger.warning(f"Document file not found for extraction: {full_path}")
                raise FileProcessingError(f"Document file not found: {full_path}", filepath=full_path)

            content = self.processor.process_files(str(full_path))
            return content

        except FileNotFoundError as e:
            self.logger.error(f"Document file not found during chunk extraction: {document_path}: {e}")
            raise FileProcessingError(f"Document file not found: {document_path}", filepath=document_path)
        except ParsingError as e:
            self.logger.error(f"Parsing error extracting content from {document_path}: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error extracting content from {document_path}: {type(e).__name__} - {e}")
            raise ParsingError(f"Unexpected error extracting content from {document_path}: {e}", filename=document_path)

    def call_llm_api(self, prompt: str, max_retries: int = 3, retry_delay: float = 1.0) -> Optional[Dict[str, Any]]:
        """Call Gemini API with the generated prompt and return parsed JSON response."""
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())

        for attempt in range(max_retries):
            try:
                self.logger.info(f"Calling Gemini API (attempt {attempt + 1}/{max_retries}) with model {self.gemini_model}")
                response = self.model.generate_content(
                    prompt,
                    generation_config=self.generation_config
                )

                response_text_for_tracker = response.text if response.text else "No response text received."
                self.api_call_tracker.log_api_call(
                    prompt=prompt,
                    response=response_text_for_tracker,
                    model=self.gemini_model,
                    timestamp=timestamp
                )

                if not response.text:
                    self.logger.error(f"Gemini API returned empty response for model {self.gemini_model} (attempt {attempt + 1})")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                    raise APIError(f"Gemini API returned empty response after {max_retries} attempts for model {self.gemini_model}.")

                response_text_cleaned = response.text.strip()
                if response_text_cleaned.startswith('```json'):
                    response_text_cleaned = response_text_cleaned[7:]
                if response_text_cleaned.endswith('```'):
                    response_text_cleaned = response_text_cleaned[:-3]
                response_text_cleaned = response_text_cleaned.strip()

                try:
                    llm_response = json.loads(response_text_cleaned)
                except json.JSONDecodeError as e:
                    self.logger.error(f"Failed to parse JSON response from Gemini: {e} - Raw: {response_text_cleaned[:200]}...")
                    raise ParsingError(f"Failed to parse JSON response from Gemini: {e}", filename="API Response")

                llm_response["llm_used_for_processing"] = f"gemini-{self.gemini_model}"
                self.logger.info("Successfully received and parsed Gemini API response.")
                return llm_response

            except ParsingError as pe:
                self.logger.error(f"JSON ParsingError in call_llm_api: {pe}")
                self.api_call_tracker.log_api_call(
                    prompt=prompt,
                    response=f"ParsingError: {str(pe)}",
                    model=self.gemini_model,
                    timestamp=timestamp
                )
                raise
            except Exception as e:
                self.logger.error(f"Error calling Gemini API on attempt {attempt + 1}/{max_retries} with model {self.gemini_model}: {type(e).__name__} - {e}")
                self.api_call_tracker.log_api_call(
                    prompt=prompt,
                    response=f"APIError or other exception: {type(e).__name__} - {str(e)}",
                    model=self.gemini_model,
                    timestamp=timestamp
                )
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (2 ** attempt))
                    continue
                raise APIError(f"Failed to call Gemini API after {max_retries} attempts with model {self.gemini_model}: {e}")

        final_error_msg = f"Failed to get valid response from Gemini API after {max_retries} attempts (loop exhausted)."
        self.logger.error(final_error_msg)
        self.api_call_tracker.log_api_call(
            prompt=prompt,
            response=final_error_msg,
            model=self.gemini_model,
            timestamp=timestamp
        )
        raise APIError(final_error_msg)

    def summarize_document(self, document: DocumentMetadata) -> Optional[Dict[str, Any]]:
        """Summarize a single document based on its category."""
        self.logger.info(f"Starting summarization for document ID: {document.id}, Filename: {document.originalFilename}")
        try:
            key_document_chunks = self.extract_document_chunks(document.storagePath)

            prompt = get_appropriate_prompt(
                document.finalCategory,
                document.originalFilename,
                document.finalCategory,
                document.finalPurpose,
                key_document_chunks
            )
            llm_response = self.call_llm_api(prompt)

            if llm_response:
                result = {
                    "document_id": document.id,
                    "document_filename": document.originalFilename,
                    "document_category": document.finalCategory,
                    "document_group": self.get_document_group(document.finalCategory).value,
                    "user_note_purpose": document.finalPurpose,
                    "processing_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                    "llm_analysis": llm_response
                }

                summary_file_name = f"{document.id}_summary.json"
                summary_file_path = Path("data/summaries") / summary_file_name
                try:
                    with open(summary_file_path, 'w', encoding='utf-8') as sf:
                        json.dump(result, sf, indent=2, ensure_ascii=False)
                    self.logger.info(f"Successfully saved individual summary for document {document.id} to {summary_file_path}")
                    result["summaryStoragePath"] = str(summary_file_path)

                    update_success = self.metadata_manager.update_document_metadata_entry(
                        document.id,
                        {"summaryStoragePath": str(summary_file_path)}
                    )
                    if not update_success:
                        self.logger.warning(f"Failed to update master_metadata.json with summaryStoragePath for document {document.id}")
                except IOError as e:
                    self.logger.error(f"IOError saving individual summary for document {document.id} to {summary_file_path}: {e}")

                self.logger.info(f"Successfully summarized document: {document.originalFilename} (ID: {document.id})")
                return result
            else:
                self.logger.error(f"LLM API call failed to return a response for document: {document.originalFilename} (ID: {document.id})")
                return None

        except (FileProcessingError, ParsingError, APIError) as e:
            self.logger.error(f"Error summarizing document {document.id} ({document.originalFilename}): {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error summarizing document {document.id} ({document.originalFilename}): {type(e).__name__} - {e}")
            raise FileProcessingError(f"Unexpected error during summarization of document {document.id}: {e}", filepath=document.storagePath)

    def process_all_documents(self) -> List[Dict[str, Any]]:
        """Process all documents found by the metadata manager."""
        self.logger.info("Starting processing of all documents for summarization.")
        all_document_objects = self.metadata_manager.get_all_document_metadata()
        results = []

        if not all_document_objects:
            self.logger.info("No documents found by metadata manager to process.")
            return results

        self.logger.info(f"Processing {len(all_document_objects)} documents found by metadata manager.")

        for document_obj in all_document_objects:
            try:
                result = self.summarize_document(document_obj)
                if result:
                    results.append(result)
                else:
                    self.logger.warning(f"Failed to process document (summarize_document returned None): {document_obj.originalFilename} (ID: {document_obj.id})")
            except Exception as e:
                self.logger.error(f"Error processing document {document_obj.id} ({document_obj.originalFilename}) in process_all_documents loop: {e}")

        self.logger.info(f"Completed processing {len(results)} documents successfully.")
        return results

    def save_summarization_results(self, results: List[Dict[str, Any]], output_path: str = "data/all_summaries_report.json"):
        """Saves a report of all summarizations, including paths to individual summary files."""
        self.logger.info(f"Saving summarization report for {len(results)} documents to {output_path}.")

        individual_summary_paths = [result.get("summaryStoragePath") for result in results if result.get("summaryStoragePath")]

        report_data = {
            "report_metadata": {
                "total_documents_processed": len(results),
                "total_summaries_successfully_saved": len(individual_summary_paths),
                "processing_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                "version": "1.1"
            },
            "individual_summary_paths": individual_summary_paths,
            "api_call_summary": self.get_api_call_summary()
        }

        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

            with open(output_path, 'w', encoding='utf-8') as file:
                json.dump(report_data, file, indent=2, ensure_ascii=False)
            self.logger.info(f"Successfully saved summarization report to {output_path}.")

        except IOError as e:
            self.logger.error(f"IOError saving summarization report to {output_path}: {e}")
            raise FileProcessingError(f"Error writing summarization report to {output_path}: {e}", filepath=output_path)
        except Exception as e:
            self.logger.error(f"Unexpected error saving summarization report to {output_path}: {e}")
            raise FileProcessingError(f"Unexpected error writing summarization report to {output_path}: {e}", filepath=output_path)

    def get_api_call_summary(self) -> Dict[str, Any]:
        """Get summary of API calls made during processing."""
        return self.api_call_tracker.get_summary()