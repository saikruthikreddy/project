# giani_pkb/services/blob_storage_service.py

from datetime import datetime, timezone
import logging
from azure.storage.blob import BlobServiceClient, ContainerClient
from azure.identity import DefaultAzureCredential
from azure.core.exceptions import ResourceExistsError, AzureError
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
            # self.blob_service_client = BlobServiceClient(
            #     account_url=config.STORAGE_ACCOUNT_URL,
            #     credential=DefaultAzureCredential(),
            # )
            # TODO: Update this to use App Service's Managed Identity which is preferred and a secure way
            # App service is already assigned a Storage Blob Data Contributor role on Azure
            self.blob_service_client = BlobServiceClient.from_connection_string(config.STORAGE_CONNECTION_STRING)
            self.containers_created = set()  # Track created containers
            logger.info("BlobStorageService initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize BlobServiceClient: {e}", exc_info=True)
            self.blob_service_client = None

    def _ensure_container_exists(self, container_name: str):
        """Ensure that the specified container exists."""
        if not self.blob_service_client:
            raise ConnectionError("Blob service client is not initialized.")

        if container_name in self.containers_created:
            return

        try:
            container_client = self.blob_service_client.get_container_client(
                container_name
            )

            try:
                container_client.get_container_properties()
                logger.debug(f"Container '{container_name}' already exists.")
            except Exception:
                # Container doesn't exist, create it
                logger.info(f"Creating container: {container_name}")
                container_client.create_container()
                logger.info(f"Successfully created container: {container_name}")

            self.containers_created.add(container_name)

        except ResourceExistsError:
            logger.debug(f"Container '{container_name}' already exists.")
            self.containers_created.add(container_name)
        except Exception as e:
            logger.error(f"Error ensuring container '{container_name}' exists: {e}")
            raise

    def upload_file(self, container_name: str, blob_name: str, data: bytes):
        """
        Uploads data to a specific blob in a container.

        Args:
            container_name (str): Name of the container
            blob_name (str): Name of the blob (file path within container)
            data (bytes): File data to upload

        Returns:
            str: URL of the uploaded blob
        """
        if not self.blob_service_client:
            raise ConnectionError("Blob service client is not initialized.")

        try:
            self._ensure_container_exists(container_name)

            blob_client = self.blob_service_client.get_blob_client(
                container=container_name, blob=blob_name
            )

            blob_client.upload_blob(
                data,
                overwrite=True,
                metadata={
                    "uploaded_by": "giani_pkb",
                    "upload_timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

            logger.info(
                f"Successfully uploaded {blob_name} to container {container_name}."
            )
            return blob_client.url

        except AzureError as e:
            logger.error(
                f"Azure error uploading {blob_name} to {container_name}: {e}",
                exc_info=True,
            )
            raise
        except Exception as e:
            logger.error(
                f"Failed to upload {blob_name} to {container_name}: {e}", exc_info=True
            )
            raise

    def download_file(self, container_name: str, blob_name: str) -> bytes:
        """
        Downloads a blob as bytes.

        Args:
            container_name (str): Name of the container
            blob_name (str): Name of the blob to download

        Returns:
            bytes: The downloaded file data
        """
        if not self.blob_service_client:
            raise ConnectionError("Blob service client is not initialized.")

        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=container_name, blob=blob_name
            )

            download_stream = blob_client.download_blob()
            return download_stream.readall()

        except Exception as e:
            logger.error(
                f"Failed to download {blob_name} from {container_name}: {e}",
                exc_info=True,
            )
            raise

    def delete_file(self, container_name: str, blob_name: str):
        """
        Deletes a blob from the container.

        Args:
            container_name (str): Name of the container
            blob_name (str): Name of the blob to delete
        """
        if not self.blob_service_client:
            raise ConnectionError("Blob service client is not initialized.")

        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=container_name, blob=blob_name
            )

            blob_client.delete_blob()
            logger.info(
                f"Successfully deleted {blob_name} from container {container_name}."
            )

        except Exception as e:
            logger.error(
                f"Failed to delete {blob_name} from {container_name}: {e}",
                exc_info=True,
            )
            raise

    def list_blobs(self, container_name: str, prefix: str = None):
        """
        List blobs in a container.

        Args:
            container_name (str): Name of the container
            prefix (str, optional): Prefix to filter blobs

        Returns:
            list: List of blob names
        """
        if not self.blob_service_client:
            raise ConnectionError("Blob service client is not initialized.")

        try:
            container_client = self.blob_service_client.get_container_client(
                container_name
            )
            blobs = container_client.list_blobs(name_starts_with=prefix)
            return [blob.name for blob in blobs]

        except Exception as e:
            logger.error(
                f"Failed to list blobs in {container_name}: {e}", exc_info=True
            )
            raise

blob_storage_service = BlobStorageService()
