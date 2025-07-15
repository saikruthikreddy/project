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
            response_schema=self._get_response_schema()
        )

    def _get_response_schema(self):
        """Return expected JSON schema."""
        return {
            "type": "object",
            "properties": {
                "ai_overall_key_themes_list": {"type": "array", "items": {"type": "string"}},
                "ai_high_level_narrative_summary": {"type": "string"},
                "ai_main_topics_with_summaries_list_of_objects": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "topic_name": {"type": "string"},
                            "topic_summary": {"type": "string"}
                        },
                        "required": ["topic_name", "topic_summary"]
                    }
                },
                "ai_key_takeaways_bullets": {"type": "array", "items": {"type": "string"}},
                "extracted_metadata": {"type": "object"},
                "extracted_keywords": {"type": "array", "items": {"type": "string"}}
            },
            "required": [
                "ai_overall_key_themes_list",
                "ai_high_level_narrative_summary",
                "ai_main_topics_with_summaries_list_of_objects",
                "ai_key_takeaways_bullets",
                "extracted_metadata",
                "extracted_keywords"
            ]
        }

    def get_document_group(self, category: str) -> DocumentGroup:
        return CATEGORY_TO_GROUP_MAPPING.get(category, DocumentGroup.GROUP_D)

    def extract_document_chunks(self, document_path: str) -> List[Dict[str, Any]]:
        """Extracts text chunks from a document."""
        if not os.path.isabs(document_path):
            document_path = os.path.join(os.getcwd(), document_path)

        if not os.path.exists(document_path):
            raise FileProcessingError(f"Document not found: {document_path}", filepath=document_path)

        try:
            parsed_blocks, _ = self.processor.process_single_file(document_path, "doc-id", "proj-id")
            if not parsed_blocks:
                return []

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

            return chunks
        except Exception as e:
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
        cleaned = raw.strip()
        if "```json" in cleaned:
            start = cleaned.find("```json") + 7
            end = cleaned.find("```json",start)
            cleaned = cleaned[start:end].strip() if end != -1 else cleaned[start:].strip()
        elif "```" in cleaned:
            start = cleaned.find("```")+7
            end = cleaned.find("```", start)
            cleaned = cleaned[start:end].strip() if end != -1 else cleaned[start:].strip()

        # Normalize brackets
        cleaned = cleaned[cleaned.find("{"):] if "{" in cleaned else cleaned
        cleaned = cleaned[:cleaned.rfind("}") + 1] if "}" in cleaned else cleaned

        # Balance braces
        if cleaned.count("{") > cleaned.count("}"):
            cleaned += "}" * (cleaned.count("{") - cleaned.count("}"))

        # Fix common errors
        cleaned = re.sub(r',\s*}', '}', cleaned)
        cleaned = re.sub(r',\s*]', ']', cleaned)

        return cleaned if cleaned.startswith("{") and cleaned.endswith("}") else None

    def validate_llm_response(self, response: Dict[str, Any]) -> bool:
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
                self.logger.error(f"Missing field in response: {field}")
                return False
            if not isinstance(response[field], field_type):
                self.logger.error(f"Type mismatch for '{field}': expected {field_type}, got {type(response[field])}")
                return False

        return True

    def call_llm_api(self, prompt: str, retries=3) -> Optional[Dict[str, Any]]:
        for attempt in range(retries):
            try:
                response = self.model.generate_content(prompt, generation_config=self.generation_config)
                if not response.text:
                    raise APIError("Empty response from LLM")

                try:
                    result = json.loads(response.text)
                except json.JSONDecodeError:
                    cleaned = self.extract_clean_json(response.text)
                    if not cleaned:
                        raise ParsingError("Unable to clean and parse JSON from LLM output")
                    result = json.loads(cleaned)

                result = self.normalize_keys(result)

                if self.validate_llm_response(result):
                    result["llm_used_for_processing"] = f"gemini-{self.model.model_name}"
                    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
                    self.api_call_tracker.log_api_call(prompt, str(result), self.model.model_name, timestamp)
                    return result

            except Exception as e:
                self.logger.warning(f"Retrying after error: {e}")
                time.sleep(2 ** attempt)

        raise APIError("LLM API failed after retries")

    def summarize_document(self, document: DocumentMetadata) -> Optional[Dict[str, Any]]:
        self.logger.info(f"Summarizing document: {document.originalFilename}")
        try:
            chunks = self.extract_document_chunks(document.storagePath)
            combined_text = "\n\n".join(chunk["text"] for chunk in chunks if chunk["text"])

            if not combined_text.strip():
                self.logger.warning("No text found in document chunks.")
                return None

            prompt = get_appropriate_prompt(
                document.finalCategory,
                document.originalFilename,
                document.finalCategory,
                document.finalPurpose,
                combined_text
            )

            llm_response = self.call_llm_api(prompt)
            if not llm_response:
                return None

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
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            result["summaryStoragePath"] = str(summary_path)

            self.metadata_manager.update_document_metadata_entry(
                document.id, {"summaryStoragePath": str(summary_path)}
            )

            return result
        except Exception as exc:
            raise FileProcessingError(f"Failed to summarize document: {exc}", filepath=document.storagePath)

    def process_all_documents(self) -> List[Dict[str, Any]]:
        self.logger.info("Processing all documents.")
        documents = self.metadata_manager.get_all_document_metadata()
        results = []

        for doc in documents:
            try:
                summary = self.summarize_document(doc)
                if summary:
                    results.append(summary)
            except Exception as e:
                self.logger.error(f"Error processing document {doc.originalFilename}: {e}")

        return results

    def save_summarization_results(self, results: List[Dict[str, Any]], output_report="data/all_summaries_report.json"):
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
            self.logger.info("Summarization report saved.")
        except Exception as e:
            raise FileProcessingError(f"Error writing report file: {e}", filepath=output_report)

    def get_api_call_summary(self) -> Dict[str, Any]:
        return self.api_call_tracker.get_summary()
