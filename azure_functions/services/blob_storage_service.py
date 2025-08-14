# giani_pkb/services/blob_storage_service.py

from datetime import datetime, timezone
import logging
from typing import Union
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

    def get_blob_info(self, blob_reference) -> dict:
        """
        Get detailed blob information including file name, extension, size, and metadata.

        Args:
            blob_reference: Can be either:
                - A full blob URL string
                - A dict with 'blob_name' and 'container_name' keys
                - A dict with 'file_url' key (full blob URL)

        Returns:
            dict: Comprehensive blob information including:
                - exists: Boolean indicating if blob exists
                - container_name: Container name
                - blob_name: Full blob path
                - file_name: Just the filename (e.g., "document.pdf")
                - file_extension: File extension (e.g., ".pdf")
                - name_without_extension: Filename without extension
                - size: File size in bytes
                - content_type: MIME type
                - last_modified: Last modification timestamp
                - created_on: Creation timestamp (if available)
                - etag: Entity tag for version control
                - metadata: Custom metadata dictionary
        """
        if not self.blob_service_client:
            raise ConnectionError("Blob service client is not initialized.")

        try:
            blob_client = None
            container_name = None
            blob_name = None

            # Handle different input formats
            if isinstance(blob_reference, str):
                # Parse URL to extract container and blob name
                from urllib.parse import urlparse
                parsed_url = urlparse(blob_reference)
                path_parts = parsed_url.path.lstrip('/').split('/', 1)

                if len(path_parts) < 2:
                    return {
                        'exists': False,
                        'error': 'Invalid blob URL format. Expected format: https://account.blob.core.windows.net/container/path/file.ext'
                    }

                container_name = path_parts[0]
                blob_name = path_parts[1]
                blob_client = self.blob_service_client.get_blob_client(
                    container=container_name,
                    blob=blob_name
                )

            elif isinstance(blob_reference, dict):
                if 'file_url' in blob_reference:
                    # Recursively call with URL string
                    return self.get_blob_info(blob_reference['file_url'])

                elif 'blob_name' in blob_reference and 'container_name' in blob_reference:
                    container_name = blob_reference['container_name']
                    blob_name = blob_reference['blob_name']
                    blob_client = self.blob_service_client.get_blob_client(
                        container=container_name,
                        blob=blob_name
                    )

                elif 'blob_name' in blob_reference:
                    # Search in common containers if container not specified
                    blob_name = blob_reference['blob_name']
                    containers_to_check = ['test-container', 'raw-documents']

                    for container in containers_to_check:
                        temp_client = self.blob_service_client.get_blob_client(
                            container=container,
                            blob=blob_name
                        )
                        if temp_client.exists():
                            blob_client = temp_client
                            container_name = container
                            break

                    if not blob_client:
                        return {
                            'exists': False,
                            'error': f'Blob not found in any checked containers: {blob_name}',
                            'blob_name': blob_name,
                            'containers_checked': containers_to_check
                        }
                else:
                    return {
                        'exists': False,
                        'error': "Dict must contain 'file_url', 'blob_name' with 'container_name', or just 'blob_name'"
                    }
            else:
                return {
                    'exists': False,
                    'error': "blob_reference must be a URL string or dict with required keys"
                }

            # Check if blob exists
            if not blob_client.exists():
                # Extract file info even if blob doesn't exist
                file_name = os.path.basename(blob_name)
                name_without_ext, file_extension = os.path.splitext(file_name)

                return {
                    'exists': False,
                    'container_name': container_name,
                    'blob_name': blob_name,
                    'file_name': file_name,
                    'file_extension': file_extension,
                    'name_without_extension': name_without_ext,
                    'url': blob_client.url,
                    'message': f'Blob does not exist at {container_name}/{blob_name}'
                }

            # Get blob properties
            properties = blob_client.get_blob_properties()

            # Extract file name components
            file_name = os.path.basename(blob_name)
            name_without_ext, file_extension = os.path.splitext(file_name)

            # Build comprehensive info dictionary
            blob_info = {
                'exists': True,
                'url': blob_client.url,
                'container_name': container_name,
                'blob_name': blob_name,
                'file_name': file_name,
                'file_extension': file_extension,
                'name_without_extension': name_without_ext,
                'size': properties.size,
                'size_human': self._format_file_size(properties.size),
                'content_type': properties.content_settings.content_type if properties.content_settings else None,
                'last_modified': properties.last_modified,
                'etag': properties.etag,
                'metadata': properties.metadata or {},
                'cache_control': properties.content_settings.cache_control if properties.content_settings else None,
                'content_disposition': properties.content_settings.content_disposition if properties.content_settings else None,
                'content_encoding': properties.content_settings.content_encoding if properties.content_settings else None,
                'content_language': properties.content_settings.content_language if properties.content_settings else None,
            }

            # Add creation time if available
            if hasattr(properties, 'creation_time') and properties.creation_time:
                blob_info['created_on'] = properties.creation_time

            # Add blob type information
            blob_info['blob_type'] = str(properties.blob_type) if hasattr(properties, 'blob_type') else None

            # Add lease information if applicable
            if hasattr(properties, 'lease') and properties.lease:
                blob_info['lease_status'] = str(properties.lease.status)
                blob_info['lease_state'] = str(properties.lease.state)

            logger.info(f"Retrieved blob info for: {container_name}/{blob_name}")
            return blob_info

        except Exception as e:
            logger.error(f"Error getting blob info: {e}", exc_info=True)
            return {
                'exists': False,
                'error': f"Failed to get blob info: {str(e)}",
                'blob_reference': str(blob_reference)
            }

    def _format_file_size(self, size_bytes: int) -> str:
        """
        Convert file size in bytes to human readable format.

        Args:
            size_bytes: Size in bytes

        Returns:
            str: Human readable size (e.g., "1.2 MB", "345 KB")
        """
        if size_bytes == 0:
            return "0 B"

        size_names = ["B", "KB", "MB", "GB", "TB"]
        import math
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_names[i]}"

    def move_file(self, source_path: str, dest_path: str,
              source_container: str = "test-container",
              dest_container: str = "raw-documents") -> dict:
        """
        Move a file from one container to another.

        Args:
            user_id: User ID for folder structure
            project_id: Project ID for folder structure
            filename: Original filename with extension
            source_container: Source container name (default: test-container)
            dest_container: Destination container name (default: raw-documents)

        Returns:
            dict: Result with success status, URLs, and any error info
        """
        if not self.blob_service_client:
            raise ConnectionError("Blob service client is not initialized.")

        # Construct blob path: userid/projectid/filename.ext
        # blob_path = f"{user_id}/{project_id}/{filename}"

        try:
            logger.info(f"Moving file from {source_container}/{source_path} to {dest_container}/{dest_path}")

            # Get source blob client
            source_blob_client = self.blob_service_client.get_blob_client(
                container=source_container,
                blob=source_path
            )

            # Check if source blob exists
            if not source_blob_client.exists():
                return {
                    'success': False,
                    'error': f"Source file not found: {source_container}/{source_path}",
                    'source_url': source_blob_client.url,
                    'dest_url': None,
                    'blob_path': source_path
                }

            # Ensure destination container exists
            self._ensure_container_exists(dest_container)

            # Get destination blob client
            dest_blob_client = self.blob_service_client.get_blob_client(
                container=dest_container,
                blob=dest_path
            )

            # Check if destination already exists
            if dest_blob_client.exists():
                logger.warning(f"Destination file already exists, will overwrite: {dest_container}/{dest_path}")

            # Copy source to destination using copy_from_url
            copy_operation = dest_blob_client.start_copy_from_url(source_blob_client.url)

            # Get copy properties to check status
            copy_properties = dest_blob_client.get_blob_properties()

            # For most cases, copy is immediate, but we should check status
            if copy_properties.copy.status == 'success':
                # Delete source blob after successful copy
                # source_blob_client.delete_blob()

                logger.info(f"Successfully moved file from {source_container} to {dest_container}")
                return {
                    'success': True,
                    'source_url': source_blob_client.url,
                    'dest_url': dest_blob_client.url,
                    'blob_path': dest_path,
                    'message': f"File moved successfully from {source_container} to {dest_container}"
                }
            elif copy_properties.copy.status == 'pending':
                # Copy is still in progress, wait a bit and check again
                import time
                time.sleep(1)
                copy_properties = dest_blob_client.get_blob_properties()

                if copy_properties.copy.status == 'success':
                    # source_blob_client.delete_blob()
                    logger.info(f"Successfully moved file from {source_container} to {dest_container}")
                    return {
                        'success': True,
                        'source_url': source_blob_client.url,
                        'dest_url': dest_blob_client.url,
                        'blob_path': dest_path,
                        'message': f"File moved successfully from {source_container} to {dest_container}"
                    }
                else:
                    return {
                        'success': False,
                        'error': f"Copy operation failed with status: {copy_properties.copy.status}",
                        'source_url': source_blob_client.url,
                        'dest_url': dest_blob_client.url,
                        'blob_path': dest_path
                    }
            else:
                return {
                    'success': False,
                    'error': f"Copy operation failed with status: {copy_properties.copy.status}",
                    'source_url': source_blob_client.url,
                    'dest_url': dest_blob_client.url,
                    'blob_path': dest_path
                }

        except Exception as e:
            logger.error(f"Error moving file from {source_container} to {dest_container}: {e}", exc_info=True)
            return {
                'success': False,
                'error': f"Move operation failed: {str(e)}",
                'source_url': None,
                'dest_url': None,
                'blob_path': dest_path
            }

    def file_exists(self, file_reference: Union[str, dict]) -> dict:
        """
        Check if a file exists at the specified location.

        Args:
            file_reference: Can be either:
                - A full blob URL string
                - A dict with 'blob_name' key (userid/projectid/name.ext format)
                - A dict with 'file_url' key (full blob URL)

        Returns:
            dict: Result with exists status, URL, and metadata if file exists
        """
        if not self.blob_service_client:
            raise ConnectionError("Blob service client is not initialized.")

        try:
            blob_client = None

            if isinstance(file_reference, str):
                # Assume it's a full URL
                blob_client = BlobClient.from_blob_url(file_reference)
                blob_path = blob_client.blob_name
                container_name = blob_client.container_name

            elif isinstance(file_reference, dict):
                if 'file_url' in file_reference:
                    # Full URL provided
                    blob_client = BlobClient.from_blob_url(file_reference['file_url'])
                    blob_path = blob_client.blob_name
                    container_name = blob_client.container_name

                elif 'blob_name' in file_reference:
                    # Blob name provided, need to determine container
                    blob_path = file_reference['blob_name']
                    # You might need to specify which container to check
                    # For now, let's check both test-container and raw-documents
                    containers_to_check = ['test-container', 'raw-documents']

                    for container in containers_to_check:
                        temp_client = self.blob_service_client.get_blob_client(
                            container=container,
                            blob=blob_path
                        )
                        if temp_client.exists():
                            blob_client = temp_client
                            container_name = container
                            break

                    if not blob_client:
                        return {
                            'exists': False,
                            'error': f"File not found in any checked containers: {blob_path}",
                            'blob_path': blob_path,
                            'containers_checked': containers_to_check
                        }
                else:
                    return {
                        'exists': False,
                        'error': "Invalid file_reference format. Expected 'file_url' or 'blob_name' key."
                    }
            else:
                return {
                    'exists': False,
                    'error': "file_reference must be a string (URL) or dict with 'file_url' or 'blob_name'"
                }

            # Check if blob exists
            if blob_client.exists():
                # Get blob properties for additional metadata
                properties = blob_client.get_blob_properties()

                logger.info(f"File exists: {container_name}/{blob_path}")
                return {
                    'exists': True,
                    'url': blob_client.url,
                    'blob_path': blob_path,
                    'container_name': container_name,
                    'size': properties.size,
                    'last_modified': properties.last_modified,
                    'content_type': properties.content_settings.content_type if properties.content_settings else None,
                    'etag': properties.etag,
                    'metadata': properties.metadata
                }
            else:
                logger.info(f"File does not exist: {container_name}/{blob_path}")
                return {
                    'exists': False,
                    'url': blob_client.url,
                    'blob_path': blob_path,
                    'container_name': container_name,
                    'message': f"File does not exist at {container_name}/{blob_path}"
                }

        except Exception as e:
            logger.error(f"Error checking file existence: {e}", exc_info=True)
            return {
                'exists': False,
                'error': f"Error checking file existence: {str(e)}",
                'file_reference': str(file_reference)
            }


blob_storage_service = BlobStorageService()
