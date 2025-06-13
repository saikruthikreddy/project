import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional # Added Optional
import logging

from giani_pkb.utils.exceptions import FileProcessingError, ParsingError, ConfigurationError # Added ConfigurationError
from giani_pkb.core.models import DocumentMetadata

logger = logging.getLogger(__name__)

MASTER_METADATA_PATH = "uploaded_documents/master_metadata.json"

class MetadataManagerService:
    def __init__(self, master_metadata_path: Optional[str] = None):
        if master_metadata_path:
            self.master_metadata_path = master_metadata_path
        else:
            self.master_metadata_path = MASTER_METADATA_PATH

        # Ensure the directory for master_metadata_path exists
        Path(self.master_metadata_path).parent.mkdir(parents=True, exist_ok=True)


    def load_master_metadata(self) -> Dict[str, Any]:
        """Load the master metadata JSON file."""
        try:
            # Check if the file exists and is not empty
            if not Path(self.master_metadata_path).is_file() or os.path.getsize(self.master_metadata_path) == 0:
                logger.info(f"Master metadata file not found or empty at {self.master_metadata_path}. Creating a new one.")
                return self._create_new_master_metadata()

            with open(self.master_metadata_path, 'r', encoding='utf-8') as file:
                data = json.load(file)

            # Basic validation for expected structure (can be expanded)
            if not isinstance(data, dict) or "documents" not in data or "total_documents" not in data:
                logger.warning(f"Master metadata file at {self.master_metadata_path} has an unexpected format. Initializing anew.")
                return self._create_new_master_metadata()

            # Compatibility for old format from OldSummary.py (totalDocuments vs total_documents)
            if "totalDocuments" in data and "total_documents" not in data: # Old format check
                 return {
                    "documents": data.get('documents', []),
                    "total_documents": data.get('totalDocuments', 0), # Map totalDocuments
                    "metadata_version": data.get('metadata_version', "0.9"), # Old version
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
            # It might be safer to raise an error or try to recover/backup the corrupted file
            raise ParsingError(f"Error parsing master metadata JSON: {e}", filename=self.master_metadata_path)
        except Exception as e:
            logger.error(f"Unexpected error loading master metadata from {self.master_metadata_path}: {e}")
            raise FileProcessingError(f"Unexpected error loading master metadata: {e}", filepath=self.master_metadata_path)

    def _get_default_statistics(self) -> Dict[str, Any]:
        return {
            "document_types": {},
            "ai_classifications": {},
            "priority_levels": {},
            "file_types": {}
        }

    def _create_new_master_metadata(self) -> Dict[str, Any]:
        """Creates a new master metadata structure."""
        return {
            "metadata_version": "1.1", # Current version
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
            # Ensure the directory exists
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
            # Optional: Check if doc_id already exists and handle update vs new logic
            # For now, we assume if ID is present, we might be updating an existing entry,
            # but the current logic appends. If updates are needed, this needs refinement.
            # For simplicity, this implementation currently always adds if called.
            # A more robust way would be to have separate add_document and update_document_entry methods.

        document_entry = {
            "document_id": doc_id,
            "original_filename": doc_meta_object.originalFilename,
            "file_path": doc_meta_object.storagePath, # Mapped from storagePath
            "document_type": doc_meta_object.categoryFolder, # Mapped from categoryFolder
            "ai_classification": doc_meta_object.finalCategory, # Mapped from finalCategory
            "priority": doc_meta_object.priority,
            "file_size": doc_meta_object.fileSize,
            "file_mime_type": doc_meta_object.fileMimeType,
            "date_added": doc_meta_object.dateAddedToGiani,
            "user_id": doc_meta_object.userID,
            "project_id": doc_meta_object.projectID,
            "document_purpose": doc_meta_object.finalPurpose, # Mapped from finalPurpose
            "metadata_file_path": doc_meta_object.storedFilename # Mapped from storedFilename
        }

        # Avoid duplicate entries if the same doc_id is processed multiple times by this method
        # This is a simple check; more sophisticated update logic might be needed
        existing_doc_index = next((index for (index, d) in enumerate(master_metadata["documents"]) if d["document_id"] == doc_id), None)
        if existing_doc_index is not None:
            master_metadata["documents"][existing_doc_index] = document_entry
        else:
            master_metadata["documents"].append(document_entry)
            master_metadata["total_documents"] = len(master_metadata["documents"]) # Only increment if new

        # Update statistics
        stats = master_metadata.get("statistics", self._get_default_statistics()) # Ensure stats exist

        doc_type = doc_meta_object.categoryFolder
        stats["document_types"][doc_type] = stats["document_types"].get(doc_type, 0) + 1

        ai_class = doc_meta_object.finalCategory
        stats["ai_classifications"][ai_class] = stats["ai_classifications"].get(ai_class, 0) + 1

        priority_val = doc_meta_object.priority
        stats["priority_levels"][priority_val] = stats["priority_levels"].get(priority_val, 0) + 1

        if doc_meta_object.originalFilename:
             file_ext = Path(doc_meta_object.originalFilename).suffix.lower()
             if file_ext: # Ensure file_ext is not empty
                stats["file_types"][file_ext] = stats["file_types"].get(file_ext, 0) + 1

        master_metadata["statistics"] = stats
        self.save_master_metadata(master_metadata)

        return doc_id

    def get_document_metadata_by_id(self, doc_id: str) -> Optional[DocumentMetadata]:
        """Retrieve a document's metadata by its ID."""
        master_metadata = self.load_master_metadata()
        for doc_data in master_metadata.get("documents", []):
            if doc_data.get("document_id") == doc_id:
                # Convert dict back to DocumentMetadata object
                # This assumes DocumentMetadata.from_dict can handle this structure
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

# Example Usage (can be removed or kept for testing)
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    # Ensure the base directory exists for the example to run without errors if master file doesn't exist
    Path(MASTER_METADATA_PATH).parent.mkdir(parents=True, exist_ok=True)

    metadata_service = MetadataManagerService()

    # Create a dummy master metadata if it doesn't exist for testing
    if not Path(MASTER_METADATA_PATH).is_file():
        metadata_service.save_master_metadata(metadata_service._create_new_master_metadata())

    print("Loading metadata:")
    meta = metadata_service.load_master_metadata()
    # print(json.dumps(meta, indent=2))

    # Example of adding a document
    sample_doc_meta = DocumentMetadata(
        id=str(uuid.uuid4()), # Provide an ID or let update_master_metadata create one
        originalFilename="test_document.pdf",
        fileSize=1024,
        fileMimeType="application/pdf",
        dateAddedToGiani=datetime.now().isoformat(),
        userID="test_user",
        projectID="test_project",
        textPreview="This is a test document.",
        finalCategory="1. Strategy Document/Deck",
        finalPurpose="To test the metadata manager.",
        priority="High",
        finalizedAt=datetime.now().isoformat(),
        storagePath="uploaded_documents/Strategy/test_document.pdf",
        categoryFolder="Strategy", # Example: "Strategy"
        storedFilename="uploaded_documents/Strategy/test_document_metadata.json", # Example
        savedAt=datetime.now().isoformat()
    )
    print(f"\nAdding/Updating document: {sample_doc_meta.originalFilename}")
    new_id = metadata_service.update_master_metadata(sample_doc_meta)
    print(f"Document ID: {new_id}")

    print("\nLoading metadata again:")
    meta = metadata_service.load_master_metadata()
    # print(json.dumps(meta, indent=2))

    print("\nSummary Text:")
    print(metadata_service.get_master_metadata_summary_text())

    retrieved_doc = metadata_service.get_document_metadata_by_id(new_id)
    if retrieved_doc:
        print(f"\nRetrieved document by ID ({new_id}): {retrieved_doc.originalFilename}")

    all_docs = metadata_service.get_all_document_metadata()
    print(f"\nTotal documents retrieved: {len(all_docs)}")

```
