import json
import os
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass, field
from enum import Enum
import logging
from giani_pkb.utils.exceptions import APIError, FileProcessingError, ParsingError, ConfigurationError
from pathlib import Path
from giani_pkb.utils.constants import DocumentCategory, DocumentGroup, CATEGORY_TO_GROUP_MAPPING
from giani_pkb.utils.prompt_loader import load_prompt_template
import google.generativeai as genai
import time
# from dotenv import load_dotenv # Will be removed # Actually removed now
from giani_pkb.utils.config import GEMINI_API_KEY, GEMINI_PRO_MODEL
from giani_pkb.preprocessing.Processing import MainProcessing

processor=MainProcessing(api_key=GEMINI_API_KEY) # Updated

# load_dotenv() # Removed

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# class DocumentCategory(Enum): ... # Removed, now imported from constants
# class DocumentGroup(Enum): ... # Removed, now imported from constants

@dataclass
class DocumentMetadata:
    id: str
    originalFilename: str
    fileSize: int
    fileMimeType: str
    dateAddedToGiani: str
    userID: str
    projectID: str
    textPreview: str
    finalCategory: str
    finalPurpose: str
    priority: str
    finalizedAt: str
    storagePath: str
    categoryFolder: str
    storedFilename: str
    savedAt: str
    # Optional fields that might be present
    tempFilePath: Optional[str] = None
    processedContent: Optional[str] = None
    extractedText: Optional[str] = None
    metadata: Optional[Dict] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DocumentMetadata':
        """Create DocumentMetadata from dictionary, handling new format and mapping fields"""
        import dataclasses

        # Map new format fields to expected fields
        field_mapping = {
            'document_id': 'id',
            'original_filename': 'originalFilename',
            'file_size': 'fileSize',
            'file_mime_type': 'fileMimeType',
            'date_added': 'dateAddedToGiani',
            'user_id': 'userID',
            'project_id': 'projectID',
            'ai_classification': 'finalCategory',
            'document_purpose': 'finalPurpose',
            'file_path': 'storagePath',
            'document_type': 'categoryFolder',
            'metadata_file_path': 'storedFilename'
        }

        # Convert data using field mapping
        converted_data = {}
        for new_key, old_key in field_mapping.items():
            if new_key in data:
                converted_data[old_key] = data[new_key]

        # Handle fields that don't have direct mappings
        converted_data.update({
            'textPreview': data.get('textPreview', 'Not available'),
            'finalizedAt': data.get('date_added', 'unknown'),
            'savedAt': data.get('date_added', 'unknown'),
        })

        # Get field information from the dataclass
        fields = {f.name: f for f in dataclasses.fields(cls)}
        filtered_data = {}

        # Process each field in the dataclass
        for field_name, field_info in fields.items():
            if field_name in converted_data:
                # Use the converted value
                filtered_data[field_name] = converted_data[field_name]
            elif field_info.default != dataclasses.MISSING:
                # Use the field's default value
                filtered_data[field_name] = field_info.default
            elif field_info.default_factory != dataclasses.MISSING:
                # Use the field's default factory
                filtered_data[field_name] = field_info.default_factory()
            else:
                # Provide sensible defaults for required fields that are missing
                if field_info.type == str or field_info.type == 'str':
                    filtered_data[field_name] = 'unknown'
                elif field_info.type == int or field_info.type == 'int':
                    filtered_data[field_name] = 0
                elif field_info.type in [dict, Dict]:
                    filtered_data[field_name] = {}
                else:
                    # For other types, try to provide a reasonable default
                    filtered_data[field_name] = 'unknown'

        return cls(**filtered_data)

class DocumentSummarizer:
    def __init__(self,
                 master_metadata_path: str = 'uploaded_documents/master_metadata.json',
                 gemini_api_key: Optional[str] = None,
                 gemini_model: str = GEMINI_PRO_MODEL): # Default to config constant
        self.master_metadata_path = master_metadata_path
        self.gemini_model = gemini_model

        # Initialize Gemini API
        current_api_key = gemini_api_key if gemini_api_key else GEMINI_API_KEY
        if not current_api_key:
            raise ConfigurationError("Gemini API key must be provided either as parameter or via GEMINI_API_KEY in config/env")

        genai.configure(api_key=current_api_key)
        self.model = genai.GenerativeModel(self.gemini_model) # Use self.gemini_model which has the default

        # Configure generation settings for better JSON output
        self.generation_config = genai.types.GenerationConfig(
            temperature=0.1,  # Low temperature for consistent output
            top_p=0.8,
            top_k=40,
            max_output_tokens=8192,
        )

        # self.category_to_group_mapping = { ... } # Removed, now imported as CATEGORY_TO_GROUP_MAPPING

    def load_master_metadata(self) -> Dict[str, Any]:
        """Load the master metadata JSON file with new format"""
        try:
            with open(self.master_metadata_path, 'r', encoding='utf-8') as file:
                data = json.load(file)

            # Handle new format - convert to expected format for compatibility
            if 'total_documents' in data:
                # New format detected
                return {
                    "documents": data.get('documents', []),
                    "totalDocuments": data.get('total_documents', 0),
                    "metadata_version": data.get('metadata_version'),
                    "created_date": data.get('created_date'),
                    "last_updated": data.get('last_updated'),
                    "statistics": data.get('statistics', {})
                }
            else:
                # Old format
                return data

        except FileNotFoundError:
            logger.error(f"Master metadata file not found: {self.master_metadata_path}")
            raise FileProcessingError(f"Master metadata file not found: {self.master_metadata_path}", filepath=self.master_metadata_path)
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing master metadata JSON: {e}")
            raise ParsingError(f"Error parsing master metadata JSON: {e}", filename=self.master_metadata_path)

    def get_document_group(self, category: str) -> DocumentGroup:
        """Determine which group a document belongs to based on its category"""
        return CATEGORY_TO_GROUP_MAPPING.get(category, DocumentGroup.GROUP_D)

    def extract_document_chunks(self, document_path: str) -> str:
        """Extract key document content chunks from the document file"""
        try:
            # Ensure the path is absolute or relative to the correct base directory
            if not os.path.isabs(document_path):
                # If it's a relative path, assume it's relative to the working directory
                full_path = os.path.join(os.getcwd(), document_path)
            else:
                full_path = document_path

            if not os.path.exists(full_path):
                logger.warning(f"Document file not found: {full_path}")
                return f"Document file not found: {full_path}"

            content = processor.process_files(str(full_path))
            return content

        except FileNotFoundError as e: # More specific for file not found
            logger.error(f"Document file not found: {document_path}: {e}")
            raise FileProcessingError(f"Document file not found: {document_path}", filepath=document_path)
        except Exception as e: # Catch other errors during processing (e.g., issues within processor.process_files)
            logger.error(f"Error extracting content from {document_path}: {e}")
            # This could be a ParsingError if processor.process_files indicates such,
            # or a more general FileProcessingError.
            raise ParsingError(f"Error extracting content from {document_path}: {e}", filename=document_path)

    def call_llm_api(self, prompt: str, max_retries: int = 3, retry_delay: float = 1.0) -> Optional[Dict[str, Any]]:
        """
        Call Gemini API with the generated prompt and return parsed JSON response
        """
        for attempt in range(max_retries):
            try:
                logger.info(f"Calling Gemini API (attempt {attempt + 1}/{max_retries})")

                # Make the API call to Gemini
                response = self.model.generate_content(
                    prompt,
                    generation_config=self.generation_config
                )

                print('The prompt passsed is here gaiss : \n', prompt)

                # Check if the response was blocked or had issues
                if not response.text:
                    logger.error("Gemini API returned empty response")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                    return None

                # Try to parse the JSON response
                try:
                    # Clean the response text - sometimes Gemini wraps JSON in markdown
                    response_text = response.text.strip()
                    if response_text.startswith('```json'):
                        response_text = response_text[7:]  # Remove ```json
                    if response_text.endswith('```'):
                        response_text = response_text[:-3]  # Remove ```

                    response_text = response_text.strip()

                    # Parse JSON
                    try:
                        # Clean the response text - sometimes Gemini wraps JSON in markdown
                        if response_text.startswith('```json'):
                            response_text = response_text[7:]  # Remove ```json
                        if response_text.endswith('```'):
                            response_text = response_text[:-3]  # Remove ```
                        response_text = response_text.strip()
                        llm_response = json.loads(response_text)
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse JSON response from Gemini: {e} - Raw: {response_text[:200]}...")
                        # No retry for parsing error, raise immediately
                        raise ParsingError(f"Failed to parse JSON response from Gemini: {e}", filename="API Response")

                    # Add model information to response
                    llm_response["llm_used_for_processing"] = f"gemini-{self.gemini_model}"

                    logger.info("Successfully received and parsed Gemini API response")
                    return llm_response

            except ParsingError as pe: # Re-raise ParsingError from JSON decoding
                logger.error(f"JSON ParsingError in call_llm_api: {pe}") # Log it here
                raise # Re-raise the original ParsingError
            except Exception as e: # Catch other API communication errors
                logger.error(f"Error calling Gemini API on attempt {attempt + 1}/{max_retries}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (2 ** attempt))  # Exponential backoff
                    continue
                # If loop finishes, all retries failed
                raise APIError(f"Failed to call Gemini API after {max_retries} attempts: {e}")

        # This part should ideally be unreachable if the loop always raises or returns.
        # However, to be safe and explicit if loop structure changes:
        logger.error(f"Failed to get valid response from Gemini API after {max_retries} attempts (reached end of function)")
        raise APIError(f"Failed to get valid response from Gemini API after {max_retries} attempts")

    def get_group_a_prompt(self, originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
        """Generate Group A prompt for Strategic & Formal Client-Facing Deliverables/Inputs"""
        prompt_template = load_prompt_template("summarization_group_a_prompt.txt")
        return prompt_template.format(
            originalFilename=originalFilename,
            documentSourceType=documentSourceType,
            userNoteOnPurpose=userNoteOnPurpose,
            key_document_chunks=key_document_chunks
        )

    def get_group_b_prompt(self, originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
        """Generate Group B prompt for Research, Analysis & Informational Inputs"""
        prompt_template = load_prompt_template("summarization_group_b_prompt.txt")
        return prompt_template.format(
            originalFilename=originalFilename,
            documentSourceType=documentSourceType,
            userNoteOnPurpose=userNoteOnPurpose,
            key_document_chunks=key_document_chunks
        )

    def get_group_c_prompt(self, originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
        """Generate Group C prompt for Project Execution & Iterative Work Products"""
        prompt_template = load_prompt_template("summarization_group_c_prompt.txt")
        return prompt_template.format(
            originalFilename=originalFilename,
            documentSourceType=documentSourceType,
            userNoteOnPurpose=userNoteOnPurpose,
            key_document_chunks=key_document_chunks
        )

    def get_group_d_prompt(self, originalFilename: str, documentSourceType: str, userNoteOnPurpose: str, key_document_chunks: str) -> str:
        """Generate Group D prompt for Conversational & Interaction Records"""
        prompt_template = load_prompt_template("summarization_group_d_prompt.txt")
        return prompt_template.format(
            originalFilename=originalFilename,
            documentSourceType=documentSourceType,
            userNoteOnPurpose=userNoteOnPurpose,
            key_document_chunks=key_document_chunks
        )

    def get_appropriate_prompt(self, document: DocumentMetadata, key_document_chunks: str) -> str:
        """Get the appropriate prompt based on document category"""
        group = self.get_document_group(document.finalCategory)

        if group == DocumentGroup.GROUP_A:
            return self.get_group_a_prompt(
                document.originalFilename,
                document.finalCategory,
                document.finalPurpose,
                key_document_chunks
            )
        elif group == DocumentGroup.GROUP_B:
            return self.get_group_b_prompt(
                document.originalFilename,
                document.finalCategory,
                document.finalPurpose,
                key_document_chunks
            )
        elif group == DocumentGroup.GROUP_C:
            return self.get_group_c_prompt(
                document.originalFilename,
                document.finalCategory,
                document.finalPurpose,
                key_document_chunks
            )
        else:  # GROUP_D
            return self.get_group_d_prompt(
                document.originalFilename,
                document.finalCategory,
                document.finalPurpose,
                key_document_chunks
            )

    def summarize_document(self, document: DocumentMetadata) -> Optional[Dict[str, Any]]:
        """Summarize a single document based on its category"""
        try:
            # Extract document content
            key_document_chunks = self.extract_document_chunks(document.storagePath)

            # Get appropriate prompt
            prompt = self.get_appropriate_prompt(document, key_document_chunks)

            # Call Gemini API
            llm_response = self.call_llm_api(prompt)

            if llm_response:
                # Add document metadata to response
                result = {
                    "document_id": document.id,
                    "document_filename": document.originalFilename,
                    "document_category": document.finalCategory,
                    "document_group": self.get_document_group(document.finalCategory).value,
                    "user_note_purpose": document.finalPurpose,
                    "processing_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                    "llm_analysis": llm_response
                }

                logger.info(f"Successfully processed document: {document.originalFilename}")
                return result
            # else: # This 'else' block is now effectively handled by call_llm_api raising an error
                # logger.error(f"Gemini API call failed for document: {document.originalFilename}")
                # return None # call_llm_api will raise APIError or ParsingError instead

        except (FileProcessingError, ParsingError, APIError) as e: # Catch known custom errors
            logger.error(f"Error summarizing document {document.id}: {e}")
            raise # Re-raise known custom error
        except Exception as e: # Catch any other unexpected error
            logger.error(f"Unexpected error summarizing document {document.id}: {e}")
            raise FileProcessingError(f"Unexpected error summarizing document {document.id}: {e}", filepath=document.storagePath)

    def process_all_documents(self) -> List[Dict[str, Any]]:
        """Process all documents in the master metadata file"""
        metadata = self.load_master_metadata()
        results = []

        logger.info(f"Processing {metadata.get('totalDocuments', 0)} documents")

        for doc_data in metadata.get('documents', []):
            try:
                # Convert dict to DocumentMetadata object using the safe method
                document = DocumentMetadata.from_dict(doc_data)

                # Summarize the document
                result = self.summarize_document(document)

                if result:
                    results.append(result)
                else:
                    logger.warning(f"Failed to process document: {document.originalFilename}")

            except Exception as e:
                logger.error(f"Error processing document {doc_data.get('document_id', doc_data.get('id', 'unknown'))}: {e}")

        return results

    def save_results(self, results: List[Dict[str, Any]], output_path: str = "summarization_results.json"):
        """Save summarization results to a JSON file"""
        try:
            output_data = {
                "summarization_results": results,
                "total_processed": len(results),
                "processing_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                "version": "1.0"
            }

            with open(output_path, 'w', encoding='utf-8') as file:
                json.dump(output_data, file, indent=2, ensure_ascii=False)

            logger.info(f"Results saved to {output_path}")

        except IOError as e: # More specific for file writing issues
            logger.error(f"Error saving results: {e}")
            raise FileProcessingError(f"Error writing results to {output_path}: {e}", filepath=output_path)
        except Exception as e: # Catch any other unexpected errors
            logger.error(f"Unexpected error saving results: {e}")
            raise FileProcessingError(f"Unexpected error writing results to {output_path}: {e}", filepath=output_path)

def main():
    """Main execution function"""
    # Initialize the summarizer with Gemini API
    # You can pass the API key directly or set GEMINI_API_KEY environment variable
    summarizer = DocumentSummarizer(
        gemini_api_key=GEMINI_API_KEY,  # Will use GEMINI_API_KEY env var from config
        gemini_model=GEMINI_PRO_MODEL  # Default from __init__ or can be specified
    )

    # Process all documents
    results = summarizer.process_all_documents()

    # Save results
    summarizer.save_results(results)

    # Print summary
    print(f"\n=== Summarization Complete ===")
    print(f"Total documents processed: {len(results)}")
    print(f"Results saved to: summarization_results.json")

    # Group results by category
    category_counts = {}
    for result in results:
        category = result.get('document_category', 'Unknown')
        category_counts[category] = category_counts.get(category, 0) + 1

    print(f"\nDocuments by category:")
    for category, count in category_counts.items():
        print(f"  - {category}: {count}")

if __name__ == "__main__":
    main()
