from abc import ABC, abstractmethod
from typing import Union, Optional


class StorageServiceBase(ABC):
    """Abstract base class defining the interface for storage services."""

    @abstractmethod
    def upload_file(self, container_name: str, blob_name: str, data: bytes) -> str:
        """
        Uploads a file with given container name and blob name.

        Args:
            container_name (str): Name of the container
            blob_name (str): Name of the blob/file
            data (bytes): File data to upload

        Returns:
            str: Path or URL of the uploaded file
        """
        pass

    @abstractmethod
    def download_file(self, container_name: str, blob_name: str) -> bytes:
        """
        Downloads a file identified by container and blob name.

        Args:
            container_name (str): Name of the container
            blob_name (str): Name of the blob/file

        Returns:
            bytes: The downloaded file data
        """
        pass

    @abstractmethod
    def delete_file(self, container_name: str, blob_name: str):
        """
        Deletes the specified file.

        Args:
            container_name (str): Name of the container
            blob_name (str): Name of the blob/file to delete
        """
        pass

    @abstractmethod
    def list_blobs(self, container_name: str, prefix: str = None) -> list:
        """
        List blobs in a container.

        Args:
            container_name (str): Name of the container
            prefix (str, optional): Prefix to filter blobs

        Returns:
            list: List of blob names
        """
        pass

    @abstractmethod
    def get_blob_info(self, blob_reference) -> dict:
        """
        Get detailed blob information including file name, extension, size, and metadata.

        Args:
            blob_reference: Can be either a URL string or dict with blob info

        Returns:
            dict: Comprehensive blob information
        """
        pass

    @abstractmethod
    def move_file(
        self,
        source_path: str,
        dest_path: str,
        source_container: str = "test-container",
        dest_container: str = "raw-documents",
    ) -> dict:
        """
        Move a file from one location to another.

        Args:
            source_path (str): Source file path
            dest_path (str): Destination file path
            source_container (str): Source container name
            dest_container (str): Destination container name

        Returns:
            dict: Result with success status and details
        """
        pass

    @abstractmethod
    def file_exists(self, file_reference: Union[str, dict]) -> dict:
        """
        Check if a file exists at the specified location.

        Args:
            file_reference: Can be either a URL string or dict with file info

        Returns:
            dict: Result with exists status and metadata
        """
        pass
