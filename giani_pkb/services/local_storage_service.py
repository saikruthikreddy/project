import os
import logging
import shutil
from datetime import datetime
from werkzeug.utils import secure_filename
from giani_pkb.utils.config import config
from giani_pkb.services.storage_service_base import StorageServiceBase

logger = logging.getLogger(__name__)

class LocalStorageService(StorageServiceBase):
    def __init__(self):
        """
        Initializes the local storage service.
        Ensures the upload directory exists.
        """
        self.upload_folder = config.UPLOAD_FOLDER
        os.makedirs(self.upload_folder, exist_ok=True)
        logger.info(f"LocalStorageService initialized. Uploads will be saved to: {self.upload_folder}")

    def _get_local_path(self, container_name: str, blob_name: str) -> str:
        """Helper method to get local file path."""
        # Create container subdirectory if it doesn't exist
        container_path = os.path.join(self.upload_folder, container_name)
        os.makedirs(container_path, exist_ok=True)

        secure_name = secure_filename(blob_name.replace("/", "_"))
        return os.path.join(container_path, secure_name)

    def upload_file(self, container_name: str, blob_name: str, data: bytes) -> str:
        """
        Saves data to a file on the local filesystem.
        """
        try:
            local_path = self._get_local_path(container_name, blob_name)
            with open(local_path, "wb") as f:
                f.write(data)
            logger.info(f"Successfully saved file to local path: {local_path}")
            return local_path
        except Exception as e:
            logger.error(f"Failed to save file locally to {blob_name}: {e}", exc_info=True)
            raise

    def download_file(self, container_name: str, blob_name: str) -> bytes:
        """
        Downloads a file from the local filesystem.
        """
        try:
            local_path = self._get_local_path(container_name, blob_name)
            with open(local_path, "rb") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to download file locally from {blob_name}: {e}", exc_info=True)
            raise

    def delete_file(self, container_name: str, blob_name: str):
        """
        Deletes a file from the local filesystem.
        """
        try:
            local_path = self._get_local_path(container_name, blob_name)
            if os.path.exists(local_path):
                os.remove(local_path)
                logger.info(f"Successfully deleted file from local path: {local_path}")
            else:
                logger.warning(f"File not found for deletion: {local_path}")
        except Exception as e:
            logger.error(f"Failed to delete file locally from {blob_name}: {e}", exc_info=True)
            raise

    def list_blobs(self, container_name: str, prefix: str = None) -> list:
        """
        List files in a local container directory.
        """
        try:
            container_path = os.path.join(self.upload_folder, container_name)
            if not os.path.exists(container_path):
                return []

            files = []
            for filename in os.listdir(container_path):
                file_path = os.path.join(container_path, filename)
                if os.path.isfile(file_path):
                    if prefix is None or filename.startswith(prefix):
                        files.append(filename)

            logger.info(f"Listed {len(files)} files in container: {container_name}")
            return files
        except Exception as e:
            logger.error(f"Failed to list files in container {container_name}: {e}", exc_info=True)
            raise

    def get_blob_info(self, blob_reference) -> dict:
        """
        Get detailed file information from local filesystem.
        """
        try:
            # Handle different input formats similar to blob storage
            container_name = None
            blob_name = None

            if isinstance(blob_reference, str):
                # Assume it's a local path or blob name
                blob_name = os.path.basename(blob_reference)
                container_name = "default"
            elif isinstance(blob_reference, dict):
                if 'blob_name' in blob_reference:
                    blob_name = blob_reference['blob_name']
                    container_name = blob_reference.get('container_name', 'default')
                else:
                    return {'exists': False, 'error': "Invalid blob_reference format"}
            else:
                return {'exists': False, 'error': "blob_reference must be string or dict"}

            local_path = self._get_local_path(container_name, blob_name)

            if not os.path.exists(local_path):
                file_name = os.path.basename(blob_name)
                name_without_ext, file_extension = os.path.splitext(file_name)
                return {
                    'exists': False,
                    'container_name': container_name,
                    'blob_name': blob_name,
                    'file_name': file_name,
                    'file_extension': file_extension,
                    'name_without_extension': name_without_ext,
                    'url': local_path,
                    'message': f'File does not exist at {local_path}'
                }

            # Get file stats
            stat = os.stat(local_path)
            file_name = os.path.basename(blob_name)
            name_without_ext, file_extension = os.path.splitext(file_name)

            return {
                'exists': True,
                'url': local_path,
                'container_name': container_name,
                'blob_name': blob_name,
                'file_name': file_name,
                'file_extension': file_extension,
                'name_without_extension': name_without_ext,
                'size': stat.st_size,
                'size_human': self._format_file_size(stat.st_size),
                'last_modified': datetime.fromtimestamp(stat.st_mtime),
                'created_on': datetime.fromtimestamp(stat.st_ctime),
                'content_type': self._get_content_type(file_extension),
                'metadata': {}
            }
        except Exception as e:
            logger.error(f"Error getting file info: {e}", exc_info=True)
            return {'exists': False, 'error': f"Failed to get file info: {str(e)}"}

    def move_file(self, source_path: str, dest_path: str,
                 source_container: str = "test-container",
                 dest_container: str = "raw-documents") -> dict:
        """
        Move a file from one location to another in local storage.
        """
        try:
            source_local_path = self._get_local_path(source_container, source_path)
            dest_local_path = self._get_local_path(dest_container, dest_path)

            if not os.path.exists(source_local_path):
                return {
                    'success': False,
                    'error': f"Source file not found: {source_local_path}",
                    'source_url': source_local_path,
                    'dest_url': dest_local_path,
                    'blob_path': source_path
                }

            # Ensure destination directory exists
            os.makedirs(os.path.dirname(dest_local_path), exist_ok=True)

            # Move the file
            shutil.move(source_local_path, dest_local_path)

            logger.info(f"Successfully moved file from {source_local_path} to {dest_local_path}")
            return {
                'success': True,
                'source_url': source_local_path,
                'dest_url': dest_local_path,
                'blob_path': dest_path,
                'message': f"File moved successfully from {source_container} to {dest_container}"
            }
        except Exception as e:
            logger.error(f"Error moving file: {e}", exc_info=True)
            return {
                'success': False,
                'error': f"Move operation failed: {str(e)}",
                'source_url': None,
                'dest_url': None,
                'blob_path': dest_path
            }

    def file_exists(self, file_reference) -> dict:
        """
        Check if a file exists in local storage.
        """
        try:
            container_name = "default"
            blob_name = None

            if isinstance(file_reference, str):
                blob_name = os.path.basename(file_reference)
            elif isinstance(file_reference, dict):
                if 'blob_name' in file_reference:
                    blob_name = file_reference['blob_name']
                    container_name = file_reference.get('container_name', 'default')
                else:
                    return {'exists': False, 'error': "Invalid file_reference format"}
            else:
                return {'exists': False, 'error': "file_reference must be string or dict"}

            local_path = self._get_local_path(container_name, blob_name)

            if os.path.exists(local_path):
                stat = os.stat(local_path)
                return {
                    'exists': True,
                    'url': local_path,
                    'blob_path': blob_name,
                    'container_name': container_name,
                    'size': stat.st_size,
                    'last_modified': datetime.fromtimestamp(stat.st_mtime),
                    'content_type': self._get_content_type(os.path.splitext(blob_name)[1]),
                    'metadata': {}
                }
            else:
                return {
                    'exists': False,
                    'url': local_path,
                    'blob_path': blob_name,
                    'container_name': container_name,
                    'message': f"File does not exist at {local_path}"
                }
        except Exception as e:
            logger.error(f"Error checking file existence: {e}", exc_info=True)
            return {
                'exists': False,
                'error': f"Error checking file existence: {str(e)}",
                'file_reference': str(file_reference)
            }

    def _format_file_size(self, size_bytes: int) -> str:
        """Convert file size to human readable format."""
        if size_bytes == 0:
            return "0 B"
        size_names = ["B", "KB", "MB", "GB", "TB"]
        import math
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_names[i]}"

    def _get_content_type(self, extension: str) -> str:
        """Get MIME type based on file extension."""
        content_types = {
            '.pdf': 'application/pdf',
            '.txt': 'text/plain',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.zip': 'application/zip'
        }
        return content_types.get(extension.lower(), 'application/octet-stream')

# Create a singleton instance for the application to use
local_storage_service = LocalStorageService()
