from giani_pkb.utils.config import config
from giani_pkb.services.blob_storage_service import blob_storage_service
from giani_pkb.services.local_storage_service import local_storage_service

def get_storage_service():
    """
    Factory function to get the appropriate storage service instance
    based on the STORAGE_BACKEND environment variable.
    """
    if config.STORAGE_BACKEND == 'azure':
        return blob_storage_service
    else: # Default to local
        return local_storage_service

# Get the active storage service instance
storage_service = get_storage_service()
