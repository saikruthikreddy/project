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
    summaryStoragePath: Optional[str] = None 
    tempFilePath: Optional[str] = None
    processedContent: Optional[str] = None
    extractedText: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = field(default_factory=dict) 

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DocumentMetadata':
        """Create DocumentMetadata from dictionary, handling new format and mapping fields"""
        import dataclasses 
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

        converted_data = {}
        for new_key, old_key in field_mapping.items():
            if new_key in data:
                converted_data[old_key] = data[new_key]

        converted_data.setdefault('textPreview', data.get('textPreview', 'Not available'))
        converted_data.setdefault('priority', data.get('priority', 'unknown')) 
        converted_data.setdefault('finalizedAt', data.get('finalizedAt', data.get('date_added', 'unknown')))
        converted_data.setdefault('savedAt', data.get('savedAt', data.get('date_added', 'unknown')))


        cls_fields = {f.name: f for f in dataclasses.fields(cls)}
        final_data = {}

        for field_name, field_info in cls_fields.items():
            if field_name in converted_data:
                final_data[field_name] = converted_data[field_name]
            elif field_info.default != dataclasses.MISSING:
                final_data[field_name] = field_info.default
            elif field_info.default_factory != dataclasses.MISSING:
                final_data[field_name] = field_info.default_factory()
            else:
                if field_info.type == str or field_info.type == 'str':
                    final_data[field_name] = 'unknown'
                elif field_info.type == int or field_info.type == 'int':
                    final_data[field_name] = 0
                elif field_info.type == Optional[str]: 
                    final_data[field_name] = None
                elif field_info.type == Optional[Dict[str, Any]]: 
                    final_data[field_name] = None 
                else:
                    final_data[field_name] = 'unknown' 

        return cls(**final_data)
