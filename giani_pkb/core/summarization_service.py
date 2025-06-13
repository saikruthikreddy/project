import json
import os
import logging
import time
from typing import Dict, List, Any, Optional

import google.generativeai as genai

from giani_pkb.core.models import DocumentMetadata
from giani_pkb.core.metadata_manager import MetadataManagerService
from giani_pkb.utils.exceptions import APIError, FileProcessingError, ParsingError, ConfigurationError
from giani_pkb.utils.constants import DocumentGroup, CATEGORY_TO_GROUP_MAPPING
from giani_pkb.utils.prompt_loader import load_prompt_template
from giani_pkb.utils.config import GEMINI_API_KEY, GEMINI_PRO_MODEL
from giani_pkb.preprocessing.Processing import MainProcessing # For extract_document_chunks

# Configure genai if not already configured (though it's often done at application entry point)
# This is a simple check; more robust application-level configuration might be preferred.
if not genai.get_model(GEMINI_PRO_MODEL): # Check if a model can be retrieved
    genai.configure(api_key=GEMINI_API_KEY)


class APICallTracker: # Definition added here
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
            "full_prompt": prompt, # Storing full prompt
            "response_preview": response[:200] + "..." if len(response) > 200 else response,
            "full_response": response, # Storing full response
            "prompt_length": len(prompt),
            "response_length": len(response)
        }
        self.api_calls.append(call_info)
        # No need to return call_info from log_api_call for this use case

    def get_summary(self) -> Dict[str, Any]: # Added type hint
        return {
            "total_api_calls": self.call_count, # Renamed for clarity
            "total_prompt_characters": sum(call["prompt_length"] for call in self.api_calls), # Renamed
            "total_response_characters": sum(call["response_length"] for call in self.api_calls), # Renamed
            "individual_api_calls": self.api_calls # Renamed
        }


class SummarizationService:
    def __init__(self,
                 master_metadata_path: Optional[str] = None,
                 gemini_api_key: Optional[str] = None,
                 gemini_model: str = GEMINI_PRO_MODEL):

        self.logger = logging.getLogger(__name__)
        self.metadata_manager = MetadataManagerService(master_metadata_path=master_metadata_path)
        self.gemini_model = gemini_model

        current_api_key = gemini_api_key if gemini_api_key else GEMINI_API_KEY
        if not current_api_key:
            self.logger.error("Gemini API key must be provided for SummarizationService.")
            raise ConfigurationError("Gemini API key must be provided either as parameter or via GEMINI_API_KEY in config/env")

        # Configure genai specifically for this instance if key was passed,
        # or rely on global config if key from env/config.
        # Note: genai.configure is global. If multiple instances with different keys are needed, this needs care.
        # For this setup, assuming one primary key for the application run.
        if gemini_api_key: # If a specific key is provided for this instance
             genai.configure(api_key=current_api_key)

        try:
            self.model = genai.GenerativeModel(self.gemini_model)
        except Exception as e:
            self.logger.error(f"Failed to initialize GenerativeModel with {self.gemini_model}: {e}")
            raise ConfigurationError(f"Failed to initialize GenerativeModel: {e}")


        self.generation_config = genai.types.GenerationConfig(
            temperature=0.1,
            top_p=0.8,
            top_k=40,
            max_output_tokens=8192,
        )

        # Initialize MainProcessing for extract_document_chunks
        self.processor = MainProcessing(api_key=current_api_key)
        self.api_call_tracker = APICallTracker() # Initialize tracker
        self.logger.info("SummarizationService initialized.")

    def get_document_group(self, category: str) -> DocumentGroup:
        """Determine which group a document belongs to based on its category."""
        return CATEGORY_TO_GROUP_MAPPING.get(category, DocumentGroup.GROUP_D)

    def extract_document_chunks(self, document_path: str) -> str:
        """Extract key document content chunks from the document file."""
        try:
            if not os.path.isabs(document_path):
                full_path = os.path.join(os.getcwd(), document_path) # Consider base path carefully
            else:
                full_path = document_path

            if not os.path.exists(full_path):
                self.logger.warning(f"Document file not found for extraction: {full_path}")
                # Return a specific string or raise FileProcessingError, matching original logic
                return f"Document file not found: {full_path}"

            # Use self.processor instance
            content = self.processor.process_files(str(full_path))
            return content

        except FileNotFoundError as e:
            self.logger.error(f"Document file not found during chunk extraction: {document_path}: {e}")
            raise FileProcessingError(f"Document file not found: {document_path}", filepath=document_path)
        except Exception as e:
            self.logger.error(f"Error extracting content from {document_path}: {e}")
            raise ParsingError(f"Error extracting content from {document_path}: {e}", filename=document_path)

    def call_llm_api(self, prompt: str, max_retries: int = 3, retry_delay: float = 1.0) -> Optional[Dict[str, Any]]:
        """Call Gemini API with the generated prompt and return parsed JSON response."""
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()) # Moved earlier as per plan

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
                # self.logger.debug(f"Prompt sent to Gemini: {prompt}") # Optional: log prompt if needed

                if not response.text:
                    self.logger.error(f"Gemini API returned empty response for model {self.gemini_model} (attempt {attempt + 1})")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                    # APIError will be caught by the generic Exception handler below, where it's logged to tracker
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
                    # Logging to tracker happens in the ParsingError handler below
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
            except Exception as e: # Includes APIError, google.api_core.exceptions etc.
                self.logger.error(f"Error calling Gemini API on attempt {attempt + 1}/{max_retries} with model {self.gemini_model}: {e}")
                self.api_call_tracker.log_api_call(
                    prompt=prompt,
                    response=f"APIError or other exception: {str(e)}", # Generalized error response
                    model=self.gemini_model,
                    timestamp=timestamp
                )
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (2 ** attempt))
                    continue
                # If all retries failed, raise the last error as APIError
                raise APIError(f"Failed to call Gemini API after {max_retries} attempts with model {self.gemini_model}: {e}")

        # Fallback if loop completes without returning/raising (should be rare)
        # This part is less likely to be hit due to exceptions being raised within the loop.
        # However, if it were, logging it to the tracker would be consistent.
        final_error_msg = f"Failed to get valid response from Gemini API after {max_retries} attempts (loop exhausted)."
        self.logger.error(final_error_msg)
        self.api_call_tracker.log_api_call(
            prompt=prompt,
            response=final_error_msg,
            model=self.gemini_model,
            timestamp=timestamp # Use the initial timestamp for this overall failure
        )
        raise APIError(final_error_msg)

    def get_group_a_prompt(self, originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
        prompt_template = load_prompt_template("summarization_group_a_prompt.txt")
        return prompt_template.format(
            originalFilename=originalFilename,
            documentSourceType=documentSourceType,
            userNoteOnPurpose=userNoteOnPurpose,
            key_document_chunks=key_document_chunks
        )

    def get_group_b_prompt(self, originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
        prompt_template = load_prompt_template("summarization_group_b_prompt.txt")
        return prompt_template.format(
            originalFilename=originalFilename,
            documentSourceType=documentSourceType,
            userNoteOnPurpose=userNoteOnPurpose,
            key_document_chunks=key_document_chunks
        )

    def get_group_c_prompt(self, originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
        prompt_template = load_prompt_template("summarization_group_c_prompt.txt")
        return prompt_template.format(
            originalFilename=originalFilename,
            documentSourceType=documentSourceType,
            userNoteOnPurpose=userNoteOnPurpose,
            key_document_chunks=key_document_chunks
        )

    def get_group_d_prompt(self, originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
        prompt_template = load_prompt_template("summarization_group_d_prompt.txt")
        return prompt_template.format(
            originalFilename=originalFilename,
            documentSourceType=documentSourceType,
            userNoteOnPurpose=userNoteOnPurpose,
            key_document_chunks=key_document_chunks
        )

    def get_appropriate_prompt(self, document: DocumentMetadata, key_document_chunks: str) -> str:
        group = self.get_document_group(document.finalCategory)
        self.logger.debug(f"Document {document.id} classified into group {group.value} based on category '{document.finalCategory}'.")

        if group == DocumentGroup.GROUP_A:
            return self.get_group_a_prompt(document.originalFilename, document.finalCategory, document.finalPurpose, key_document_chunks)
        elif group == DocumentGroup.GROUP_B:
            return self.get_group_b_prompt(document.originalFilename, document.finalCategory, document.finalPurpose, key_document_chunks)
        elif group == DocumentGroup.GROUP_C:
            return self.get_group_c_prompt(document.originalFilename, document.finalCategory, document.finalPurpose, key_document_chunks)
        else:  # GROUP_D
            return self.get_group_d_prompt(document.originalFilename, document.finalCategory, document.finalPurpose, key_document_chunks)

    def summarize_document(self, document: DocumentMetadata) -> Optional[Dict[str, Any]]:
        """Summarize a single document based on its category."""
        self.logger.info(f"Starting summarization for document ID: {document.id}, Filename: {document.originalFilename}")
        try:
            key_document_chunks = self.extract_document_chunks(document.storagePath)
            if key_document_chunks.startswith("Document file not found:"): # Check specific message from extract_document_chunks
                 self.logger.error(f"Summarization failed for {document.id}: {key_document_chunks}")
                 # Depending on desired behavior, either return None or raise specific error
                 # For now, let's mimic original behavior of possibly continuing if other errors are not raised
                 return None


            prompt = self.get_appropriate_prompt(document, key_document_chunks)
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
                self.logger.info(f"Successfully summarized document: {document.originalFilename} (ID: {document.id})")
                return result
            else:
                # This case should be covered by call_llm_api raising an error if it can't get a valid response.
                self.logger.error(f"LLM API call failed to return a response for document: {document.originalFilename} (ID: {document.id})")
                return None

        except (FileProcessingError, ParsingError, APIError) as e:
            self.logger.error(f"Error summarizing document {document.id} ({document.originalFilename}): {e}")
            # Optionally, re-raise or handle by returning None or a specific error structure
            raise # Re-raise the caught known errors
        except Exception as e:
            self.logger.error(f"Unexpected error summarizing document {document.id} ({document.originalFilename}): {e}")
            raise FileProcessingError(f"Unexpected error summarizing document {document.id}: {e}", filepath=document.storagePath)


    def process_all_documents(self) -> List[Dict[str, Any]]:
        """Process all documents found by the metadata manager."""
        self.logger.info("Starting processing of all documents for summarization.")
        # Use get_all_document_metadata which returns List[DocumentMetadata]
        all_document_objects = self.metadata_manager.get_all_document_metadata()
        results = []

        if not all_document_objects:
            self.logger.info("No documents found by metadata manager to process.")
            return results

        self.logger.info(f"Processing {len(all_document_objects)} documents found by metadata manager.")

        for document_obj in all_document_objects:
            try:
                # document_obj is already a DocumentMetadata instance
                result = self.summarize_document(document_obj)
                if result:
                    results.append(result)
                else:
                    self.logger.warning(f"Failed to process document (summarize_document returned None): {document_obj.originalFilename} (ID: {document_obj.id})")
            except Exception as e: # Catch exceptions from summarize_document if they weren't re-raised or to add context
                self.logger.error(f"Error processing document {document_obj.id} ({document_obj.originalFilename}) in process_all_documents loop: {e}")

        self.logger.info(f"Finished processing all documents. {len(results)} summaries generated.")
        return results

    def save_summarization_results(self, results: List[Dict[str, Any]], output_path: str = "summarization_results.json"):
        """Save summarization results to a JSON file."""
        self.logger.info(f"Saving {len(results)} summarization results to {output_path}.")
        try:
            output_data = {
                "summarization_results": results,
                "total_processed": len(results),
                "processing_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                "version": "1.0" # Consider making version a class or global constant
            }
            # Ensure directory for output_path exists
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

            with open(output_path, 'w', encoding='utf-8') as file:
                json.dump(output_data, file, indent=2, ensure_ascii=False)
            self.logger.info(f"Successfully saved results to {output_path}.")

        except IOError as e:
            self.logger.error(f"IOError saving summarization results to {output_path}: {e}")
            raise FileProcessingError(f"Error writing results to {output_path}: {e}", filepath=output_path)
        except Exception as e:
            self.logger.error(f"Unexpected error saving summarization results to {output_path}: {e}")
            raise FileProcessingError(f"Unexpected error writing results to {output_path}: {e}", filepath=output_path)

    def get_api_call_summary(self) -> Dict[str, Any]:
        return self.api_call_tracker.get_summary()

```
