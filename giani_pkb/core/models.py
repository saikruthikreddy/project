from dataclasses import dataclass, field
from typing import Dict, Any, Optional

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
    summaryStoragePath: Optional[str] = None # Path to the individual summary JSON
    # Optional fields that might be present
    tempFilePath: Optional[str] = None
    processedContent: Optional[str] = None
    extractedText: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = field(default_factory=dict) # Corrected typing for Dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DocumentMetadata':
        """Create DocumentMetadata from dictionary, handling new format and mapping fields"""
        import dataclasses # Moved import inside method as it's only used here

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
        # Ensure all fields expected by the __init__ are present or have defaults
        converted_data.setdefault('textPreview', data.get('textPreview', 'Not available'))
        converted_data.setdefault('priority', data.get('priority', 'unknown')) # Added missing priority
        converted_data.setdefault('finalizedAt', data.get('finalizedAt', data.get('date_added', 'unknown')))
        converted_data.setdefault('savedAt', data.get('savedAt', data.get('date_added', 'unknown')))


        # Get field information from the dataclass
        cls_fields = {f.name: f for f in dataclasses.fields(cls)}
        final_data = {}

        # Process each field in the dataclass
        for field_name, field_info in cls_fields.items():
            if field_name in converted_data:
                final_data[field_name] = converted_data[field_name]
            elif field_info.default != dataclasses.MISSING:
                final_data[field_name] = field_info.default
            elif field_info.default_factory != dataclasses.MISSING:
                final_data[field_name] = field_info.default_factory()
            else:
                # This case should ideally not be hit if all fields are handled
                # or have defaults in the dataclass definition itself.
                # For safety, providing a default based on type.
                if field_info.type == str or field_info.type == 'str':
                    final_data[field_name] = 'unknown'
                elif field_info.type == int or field_info.type == 'int':
                    final_data[field_name] = 0
                elif field_info.type == Optional[str]: # Handle Optional types
                    final_data[field_name] = None
                elif field_info.type == Optional[Dict[str, Any]]: # Handle Optional Dict
                    final_data[field_name] = None # Or field(default_factory=dict) if appropriate
                # Add more specific type handling if needed
                else:
                    final_data[field_name] = 'unknown' # Fallback

        return cls(**final_data)
