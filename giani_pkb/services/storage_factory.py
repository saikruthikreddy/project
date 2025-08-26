import logging
import os
from typing import Union
from giani_pkb.utils.config import config
from giani_pkb.services.blob_storage_service import blob_storage_service
from giani_pkb.services.local_storage_service import local_storage_service
from giani_pkb.services.storage_service_base import StorageServiceBase

logger = logging.getLogger(__name__)

class StorageFactory:
    """Factory class to provide the appropriate storage service based on environment."""

    _storage_service: StorageServiceBase = None

    @classmethod
    def get_storage_service(cls) -> StorageServiceBase:
        """
        Get the appropriate storage service based on environment configuration.

        Returns:
            StorageServiceBase: Storage service instance (BlobStorageService or LocalStorageService)
        """
        if cls._storage_service is None:
            cls._storage_service = cls._create_storage_service()
        return cls._storage_service

    @classmethod
    def _create_storage_service(cls) -> StorageServiceBase:
        """
        Create and return the appropriate storage service based on environment variables.

        Environment Variables Checked (in order of priority):
        1. USE_BLOB_STORAGE - Direct flag to use blob storage
        2. ENVIRONMENT - Environment name (prod/production/azure uses blob storage)
        3. STORAGE_CONNECTION_STRING - If storage connection string exists

        Returns:
            StorageServiceBase: The appropriate storage service instance
        """
        try:
            use_blob_storage = getattr(config, "USE_BLOB_STORAGE", False)
            if use_blob_storage:
                logger.info("USE_BLOB_STORAGE=True - Initializing Blob Storage Service")
                return blob_storage_service

            environment = getattr(config, "ENVIRONMENT", "development").lower()
            if environment in ["production", "prod"]:
                logger.info(f"Environment '{environment}' detected - Initializing Blob Storage Service")
                return blob_storage_service

            storage_conn = getattr(config, "STORAGE_CONNECTION_STRING")

            if storage_conn:
                logger.info("Azure storage connection string found - Initializing Blob Storage Service")
                return blob_storage_service

            logger.info("No blob storage indicators found - Initializing Local Storage Service for development")
            return local_storage_service

        except Exception as e:
            logger.error(f"Error determining storage service: {e}", exc_info=True)
            logger.warning("Exception occurred - Falling back to Local Storage Service")
            return local_storage_service

    @classmethod
    def _get_env_bool(cls, key: str, default: bool = False) -> bool:
        """
        Get environment variable as boolean.

        Args:
            key: Environment variable name
            default: Default value if not found

        Returns:
            bool: Environment variable value as boolean
        """
        try:
            # First check environment variables
            env_value = os.environ.get(key)
            if env_value is not None:
                return env_value.lower() in ("true", "1", "yes", "on", "enabled")

            # Then check config object
            if hasattr(config, key):
                config_value = getattr(config, key)
                if isinstance(config_value, bool):
                    return config_value
                if isinstance(config_value, str):
                    return config_value.lower() in ("true", "1", "yes", "on", "enabled")

            return default
        except Exception:
            return default

    @classmethod
    def reset(cls):
        """Reset the storage service instance (useful for testing)"""
        cls._storage_service = None
        logger.info("Storage service instance reset")

    @classmethod
    def force_service(cls, service: StorageServiceBase):
        """
        Force a specific storage service (useful for testing).

        Args:
            service: Storage service instance to use
        """
        cls._storage_service = service
        logger.info(f"Storage service forced to: {service.__class__.__name__}")

    @classmethod
    def get_current_service_type(cls) -> str:
        """
        Get the type of currently configured storage service.

        Returns:
            str: Service type name
        """
        service = cls.get_storage_service()
        return service.__class__.__name__


storage_service = StorageFactory.get_storage_service()
