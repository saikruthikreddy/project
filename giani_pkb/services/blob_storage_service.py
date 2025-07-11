# giani_pkb/services/blob_storage_service.py

import logging
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential
from giani_pkb.utils.config import config

logger = logging.getLogger(__name__)

class BlobStorageService:
    def __init__(self):
        """
        Initializes the BlobServiceClient using the managed identity.
        """
        try:
            # DefaultAzureCredential will automatically use the App Service's Managed Identity
            # when running in Azure. For local dev, it uses your logged-in Azure CLI user.
            self.blob_service_client = BlobServiceClient(
                account_url=config.STORAGE_ACCOUNT_URL,
                credential=DefaultAzureCredential(),
            )
            logger.info("BlobStorageService initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize BlobServiceClient: {e}", exc_info=True)
            self.blob_service_client = None

    def upload_file(self, container_name: str, blob_name: str, data: bytes):
        """
        Uploads data to a specific blob in a container.
        """
        if not self.blob_service_client:
            raise ConnectionError("Blob service client is not initialized.")

        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=container_name, blob=blob_name
            )
            blob_client.upload_blob(data, overwrite=True)
            logger.info(
                f"Successfully uploaded {blob_name} to container {container_name}."
            )
            return blob_client.url
        except Exception as e:
            logger.error(
                f"Failed to upload {blob_name} to {container_name}: {e}", exc_info=True
            )
            raise

# Create a singleton instance for the application to use
blob_storage_service = BlobStorageService()
