import os
import logging
from werkzeug.utils import secure_filename
from giani_pkb.utils.config import config

logger = logging.getLogger(__name__)

class LocalStorageService:
    def __init__(self):
        """
        Initializes the local storage service.
        Ensures the upload directory exists.
        """
        self.upload_folder = config.UPLOAD_FOLDER
        os.makedirs(self.upload_folder, exist_ok=True)
        logger.info(f"LocalStorageService initialized. Uploads will be saved to: {self.upload_folder}")

    def upload_file(self, container_name: str, blob_name: str, data: bytes):
        """
        Saves data to a file on the local filesystem.
        The 'container_name' and 'blob_name' parameters are kept for interface compatibility,
        but we will save files directly into the configured UPLOAD_FOLDER.

        Args:
            container_name (str): Ignored for local storage, kept for compatibility.
            blob_name (str): The unique name for the file, which will be used as the local filename.
            data (bytes): The file content to save.

        Returns:
            str: The local path where the file was saved.
        """
        try:
            # Ensure the blob_name is a secure filename to prevent path traversal issues
            secure_name = secure_filename(blob_name.replace("/", "_"))
            local_path = os.path.join(self.upload_folder, secure_name)

            with open(local_path, "wb") as f:
                f.write(data)

            logger.info(f"Successfully saved file to local path: {local_path}")
            return local_path
        except Exception as e:
            logger.error(f"Failed to save file locally to {blob_name}: {e}", exc_info=True)
            raise

# Create a singleton instance for the application to use
local_storage_service = LocalStorageService()
