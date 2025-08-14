import logging
from giani_pkb.utils.config import config
from giani_pkb.services.blob_storage_service import blob_storage_service
from giani_pkb.services.local_storage_service import local_storage_service

logger = logging.getLogger(__name__)


class StorageFactory:
    """Factory class to provide the appropriate storage service based on environment."""

    _storage_service = None

    @classmethod
    def get_storage_service(cls):
        """
        Get the appropriate storage service based on environment configuration.

        Returns:
            Storage service instance (BlobStorageService or LocalStorageService)
        """
        if cls._storage_service is None:
            cls._storage_service = cls._create_storage_service()

        return cls._storage_service

    @classmethod
    def _create_storage_service(cls):
        """Create and return the appropriate storage service."""
        try:
            use_blob_storage = getattr(config, "USE_BLOB_STORAGE", False)
            environment = getattr(config, "ENVIRONMENT", "development").lower()

            if use_blob_storage or environment in ["production", "prod", "azure"]:
                logger.info(
                    "Initializing Blob Storage Service for production environment"
                )
                return blob_storage_service
            else:
                logger.info(
                    "Initializing Local Storage Service for development environment"
                )
                return local_storage_service

        except Exception as e:
            logger.error(f"Error initializing storage service: {e}")
            logger.warning("Falling back to Local Storage Service")
            return local_storage_service

    @classmethod
    def reset(cls):
        """Reset the storage service"""
        cls._storage_service = None


storage_service = StorageFactory.get_storage_service()
