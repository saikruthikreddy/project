"""
Metadata management service for handling document metadata operations.
"""
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
import logging

from models.document import DocumentMetadata
from utils.exceptions import FileProcessingError, ParsingError

logger = logging.getLogger(__name__)

MASTER_METADATA_PATH = "data/master_metadata.json"

class MetadataManagerService:
    """
    Service for managing document metadata operations including CRUD operations
    and metadata persistence to JSON files.
    """
    def __init__(self, master_metadata_path: Optional[str] = None):
        """
        Initialize the MetadataManagerService.

        Args:
            master_metadata_path: Optional custom path for master metadata file
        """
        if master_metadata_path:
            self.master_metadata_path = master_metadata_path
        else:
            self.master_metadata_path = MASTER_METADATA_PATH

        # Path(self.master_metadata_path).parent.mkdir(parents=True, exist_ok=True)
        # Path("data/uploaded_documents").mkdir(parents=True, exist_ok=True)

    def load_master_metadata(self) -> Dict[str, Any]:
        """Load the master metadata JSON file."""
        try:
            if not Path(self.master_metadata_path).is_file() or os.path.getsize(self.master_metadata_path) == 0:
                logger.info(f"Master metadata file not found or empty at {self.master_metadata_path}. Creating a new one.")
                return self._create_new_master_metadata()

            with open(self.master_metadata_path, 'r', encoding='utf-8') as file:
                data = json.load(file)

            if not isinstance(data, dict) or "documents" not in data or "total_documents" not in data:
                logger.warning(f"Master metadata file at {self.master_metadata_path} has an unexpected format. Initializing anew.")
                return self._create_new_master_metadata()

            if "totalDocuments" in data and "total_documents" not in data:
                 return {
                    "documents": data.get('documents', []),
                    "total_documents": data.get('totalDocuments', 0),
                    "metadata_version": data.get('metadata_version', "0.9"),
                    "created_date": data.get('created_date', datetime.now().isoformat()),
                    "last_updated": data.get('last_updated', datetime.now().isoformat()),
                    "statistics": data.get('statistics', self._get_default_statistics())
                }
            return data

        except FileNotFoundError:
            logger.info(f"Master metadata file not found at {self.master_metadata_path}. Creating a new one.")
            return self._create_new_master_metadata()
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing master metadata JSON from {self.master_metadata_path}: {e}. Returning new metadata structure.")
            raise ParsingError(f"Error parsing master metadata JSON: {e}", filename=self.master_metadata_path)
        except Exception as e:
            logger.error(f"Unexpected error loading master metadata from {self.master_metadata_path}: {e}")
            raise FileProcessingError(f"Unexpected error loading master metadata: {e}", filepath=self.master_metadata_path)

    def _get_default_statistics(self) -> Dict[str, Any]:
        """Get default statistics structure."""
        return {
            "document_types": {},
            "ai_classifications": {},
            "priority_levels": {},
            "file_types": {}
        }

    def _create_new_master_metadata(self) -> Dict[str, Any]:
        """Creates a new master metadata structure."""
        return {
            "metadata_version": "1.1",
            "created_date": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "total_documents": 0,
            "documents": [],
            "statistics": self._get_default_statistics()
        }

    def save_master_metadata(self, master_metadata: Dict[str, Any]):
        """Save master metadata to file."""
        master_metadata["last_updated"] = datetime.now().isoformat()
        try:
            Path(self.master_metadata_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self.master_metadata_path, 'w', encoding='utf-8') as f:
                json.dump(master_metadata, f, indent=2, ensure_ascii=False)
            logger.info(f"Master metadata saved to {self.master_metadata_path}")
        except IOError as e:
            logger.error(f"IOError saving master metadata to {self.master_metadata_path}: {e}")
            raise FileProcessingError(f"Error saving master metadata: {e}", filepath=self.master_metadata_path)
        except Exception as e:
            logger.error(f"Unexpected error saving master metadata to {self.master_metadata_path}: {e}")
            raise FileProcessingError(f"Unexpected error saving master metadata: {e}", filepath=self.master_metadata_path)

    def update_master_metadata(self, doc_meta_object: DocumentMetadata) -> str:
        """Update master metadata with new document information and return the document ID."""
        master_metadata = self.load_master_metadata()

        if not doc_meta_object.id:
            doc_id = str(uuid.uuid4())
            doc_meta_object.id = doc_id
        else:
            doc_id = doc_meta_object.id

        document_entry = {
            "document_id": doc_id,
            "original_filename": doc_meta_object.originalFilename,
            "file_path": doc_meta_object.storagePath,
            "document_type": doc_meta_object.categoryFolder,
            "ai_classification": doc_meta_object.finalCategory,
            "priority": doc_meta_object.priority,
            "file_size": doc_meta_object.fileSize,
            "file_mime_type": doc_meta_object.fileMimeType,
            "date_added": doc_meta_object.dateAddedToGiani,
            "user_id": doc_meta_object.userID,
            "project_id": doc_meta_object.projectID,
            "document_purpose": doc_meta_object.finalPurpose,
            "metadata_file_path": doc_meta_object.storedFilename,
            "source": doc_meta_object.source
        }

        existing_doc_index = next((index for (index, d) in enumerate(master_metadata["documents"]) if d["document_id"] == doc_id), None)
        if existing_doc_index is not None:
            master_metadata["documents"][existing_doc_index] = document_entry
        else:
            master_metadata["documents"].append(document_entry)
            master_metadata["total_documents"] = len(master_metadata["documents"])

        stats = master_metadata.get("statistics", self._get_default_statistics())

        doc_type = doc_meta_object.categoryFolder
        stats["document_types"][doc_type] = stats["document_types"].get(doc_type, 0) + 1

        ai_class = doc_meta_object.finalCategory
        stats["ai_classifications"][ai_class] = stats["ai_classifications"].get(ai_class, 0) + 1

        priority_val = doc_meta_object.priority
        stats["priority_levels"][priority_val] = stats["priority_levels"].get(priority_val, 0) + 1

        if doc_meta_object.originalFilename:
             file_ext = Path(doc_meta_object.originalFilename).suffix.lower()
             if file_ext:
                stats["file_types"][file_ext] = stats["file_types"].get(file_ext, 0) + 1

        master_metadata["statistics"] = stats
        self.save_master_metadata(master_metadata)

        return doc_id

    def update_document_metadata_entry(self, document_id: str, updates: Dict[str, Any]) -> bool:
        """
        Update specific fields for a document entry in master_metadata.json.
        Note: This method updates the raw dictionary entry in master_metadata.
        It does not directly interact with DocumentMetadata objects after loading.
        """
        try:
            master_metadata = self.load_master_metadata()
            document_found = False
            for doc_entry in master_metadata.get("documents", []):
                if doc_entry.get("document_id") == document_id:
                    for key, value in updates.items():
                        doc_entry[key] = value
                    document_found = True
                    break

            if document_found:
                self.save_master_metadata(master_metadata)
                logger.info(f"Successfully updated metadata for document ID: {document_id} with fields: {list(updates.keys())}")
                return True
            else:
                logger.warning(f"Document ID: {document_id} not found in master metadata. No update performed.")
                return False
        except Exception as e:
            logger.error(f"Failed to update metadata for document ID: {document_id}. Error: {e}")
            return False

    def get_document_metadata_by_id(self, doc_id: str) -> Optional[DocumentMetadata]:
        """Retrieve a document's metadata by its ID."""
        master_metadata = self.load_master_metadata()
        for doc_data in master_metadata.get("documents", []):
            if doc_data.get("document_id") == doc_id:
                return DocumentMetadata.from_dict(doc_data)
        return None

    def get_all_document_metadata(self) -> list[DocumentMetadata]:
        """Retrieve all document metadata objects."""
        master_metadata = self.load_master_metadata()
        return [DocumentMetadata.from_dict(doc_data) for doc_data in master_metadata.get("documents", [])]

    def get_master_metadata_summary_text(self) -> str:
        """Get a textual summary of the master metadata for display."""
        master_metadata = self.load_master_metadata()

        summary = f"""
        📊 **Document Library Summary**

        **Total Documents**: {master_metadata.get('total_documents', 0)}
        **Last Updated**: {master_metadata.get('last_updated', 'Never')}

        **Document Types**:
        """

        for doc_type, count in master_metadata.get("statistics", {}).get("document_types", {}).items():
            summary += f"\n  • {doc_type}: {count}"

        summary += "\n\n**AI Classifications**:"
        for ai_class, count in sorted(master_metadata.get("statistics", {}).get("ai_classifications", {}).items()):
            summary += f"\n  • {ai_class}: {count}"

        summary += "\n\n**Priority Distribution**:"
        for priority, count in master_metadata.get("statistics", {}).get("priority_levels", {}).items():
            summary += f"\n  • {priority}: {count}"

        return summary