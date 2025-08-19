"""
Azure AI Search Service Module for Giani AI Project Knowledge Base

This module provides integration with Azure AI Search for document indexing,
searching, and retrieval with semantic capabilities.
"""

import os
import json
import logging
from typing import List, Dict, Any, Optional, Union
from datetime import datetime
import asyncio
import uuid

from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.models import VectorizedQuery
from azure.search.documents.indexes.models import (
    SearchIndex,
    SearchField,
    SearchFieldDataType,
    SimpleField,
    SearchableField,
    ComplexField,
    VectorSearch,
    HnswAlgorithmConfiguration,
    VectorSearchProfile,
    SemanticConfiguration,
    SemanticSearch,
    SemanticPrioritizedFields,
    SemanticField
)
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ResourceNotFoundError, ResourceExistsError

from ..utils.config import Config
from ..utils.exceptions import SearchServiceError
from ..utils.gemini_client import GeminiClient


class AzureSearchService:
    """
    Azure AI Search service for document indexing and retrieval.
    Integrates with the existing Giani AI project structure.
    """

    def __init__(self):
        """Initialize Azure AI Search service."""
        self.config = Config()
        self.logger = logging.getLogger(__name__)

        # Azure Search configuration
        self.service_name = os.getenv('AZURE_SEARCH_SERVICE_NAME')
        self.service_url = os.getenv('AZURE_SEARCH_SERVICE_URL')
        self.api_key = os.getenv('AZURE_SEARCH_API_KEY')
        self.api_version = os.getenv('AZURE_SEARCH_API_VERSION', '2023-11-01')

        if not all([self.service_name, self.service_url, self.api_key]):
            raise SearchServiceError("Missing Azure Search configuration in environment variables")

        # Initialize clients
        self.credential = AzureKeyCredential(self.api_key)
        self.index_client = SearchIndexClient(
            endpoint=self.service_url,
            credential=self.credential
        )

        # Index configuration
        self.index_name = "giani-documents-index"
        self.vector_dimension = 768  # Adjust based on your embedding model

        # Initialize Gemini client for embeddings
        self.gemini_client = GeminiClient()

        # Initialize search client (will be set after index creation)
        self.search_client = None

    async def initialize_index(self) -> bool:
        """
        Initialize the search index with proper schema.

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Check if index exists
            try:
                existing_index = self.index_client.get_index(self.index_name)
                self.logger.info(f"Index '{self.index_name}' already exists")
                self._initialize_search_client()
                return True
            except ResourceNotFoundError:
                pass

            # Create new index
            index = self._create_index_schema()
            self.index_client.create_index(index)
            self.logger.info(f"Created new index: {self.index_name}")

            self._initialize_search_client()
            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize index: {str(e)}")
            raise SearchServiceError(f"Index initialization failed: {str(e)}")

    def _initialize_search_client(self):
        """Initialize the search client for the index."""
        self.search_client = SearchClient(
            endpoint=self.service_url,
            index_name=self.index_name,
            credential=self.credential
        )

    def _create_index_schema(self) -> SearchIndex:
        """
        Create the search index schema optimized for document chunks.

        Returns:
            SearchIndex: The configured search index
        """
        # Define fields
        fields = [
            # Primary key
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),

            # Document identification
            SimpleField(name="project_id", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="document_id", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="document_name", type=SearchFieldDataType.String, searchable=True),
            SimpleField(name="file_type", type=SearchFieldDataType.String, filterable=True),

            # Chunk information
            SearchableField(name="content", type=SearchFieldDataType.String, searchable=True),
            SimpleField(name="chunk_id", type=SearchFieldDataType.String),
            SimpleField(name="chunk_index", type=SearchFieldDataType.Int32, filterable=True),
            SimpleField(name="chunk_size", type=SearchFieldDataType.Int32),

            # Content analysis
            SearchableField(name="summary", type=SearchFieldDataType.String, searchable=True),
            SimpleField(name="classification", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="content_type", type=SearchFieldDataType.String, filterable=True),

            # Metadata
            SearchableField(name="keywords", type=SearchFieldDataType.Collection(SearchFieldDataType.String), searchable=True),
            SimpleField(name="language", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="confidence_score", type=SearchFieldDataType.Double, filterable=True),

            # Vector fields for semantic search
            SearchField(
                name="content_vector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=self.vector_dimension,
                vector_search_profile_name="content-vector-profile"
            ),

            # Timestamps
            SimpleField(name="created_at", type=SearchFieldDataType.DateTimeOffset, filterable=True, sortable=True),
            SimpleField(name="updated_at", type=SearchFieldDataType.DateTimeOffset, filterable=True, sortable=True),

            # Additional metadata as JSON
            SimpleField(name="additional_metadata", type=SearchFieldDataType.String)
        ]

        # Configure vector search
        vector_search = VectorSearch(
            algorithms=[
                HnswAlgorithmConfiguration(
                    name="hnsw-algorithm",
                    parameters={
                        "m": 4,
                        "efConstruction": 400,
                        "efSearch": 500,
                        "metric": "cosine"
                    }
                )
            ],
            profiles=[
                VectorSearchProfile(
                    name="content-vector-profile",
                    algorithm_configuration_name="hnsw-algorithm"
                )
            ]
        )

        # Configure semantic search
        semantic_config = SemanticConfiguration(
            name="giani-semantic-config",
            prioritized_fields=SemanticPrioritizedFields(
                title_field=SemanticField(field_name="document_name"),
                content_fields=[
                    SemanticField(field_name="content"),
                    SemanticField(field_name="summary")
                ],
                keywords_fields=[SemanticField(field_name="keywords")]
            )
        )

        semantic_search = SemanticSearch(configurations=[semantic_config])

        # Create and return the index
        return SearchIndex(
            name=self.index_name,
            fields=fields,
            vector_search=vector_search,
            semantic_search=semantic_search
        )

    async def index_document_chunk(
        self,
        project_id: str,
        document_id: str,
        document_name: str,
        chunk_data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Index a single document chunk.

        Args:
            project_id: Project identifier
            document_id: Document identifier
            document_name: Name of the document
            chunk_data: Chunk information including content, summary, etc.
            metadata: Additional metadata

        Returns:
            bool: True if successful
        """
        try:
            if not self.search_client:
                await self.initialize_index()

            # Generate embedding for the content
            content = chunk_data.get('content', '')
            content_vector = await self._generate_embedding(content)

            # Prepare document for indexing
            search_document = {
                "id": str(uuid.uuid4()),
                "project_id": project_id,
                "document_id": document_id,
                "document_name": document_name,
                "file_type": metadata.get('file_type', 'unknown') if metadata else 'unknown',
                "content": content,
                "chunk_id": chunk_data.get('chunk_id', ''),
                "chunk_index": chunk_data.get('chunk_index', 0),
                "chunk_size": len(content),
                "summary": chunk_data.get('summary', ''),
                "classification": chunk_data.get('classification', ''),
                "content_type": chunk_data.get('content_type', ''),
                "keywords": chunk_data.get('keywords', []),
                "language": chunk_data.get('language', 'en'),
                "confidence_score": chunk_data.get('confidence_score', 0.0),
                "content_vector": content_vector,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
                "additional_metadata": json.dumps(metadata or {})
            }

            # Upload document to index
            result = self.search_client.upload_documents([search_document])

            if result[0].succeeded:
                self.logger.info(f"Successfully indexed chunk for document {document_id}")
                return True
            else:
                self.logger.error(f"Failed to index chunk: {result[0].error_message}")
                return False

        except Exception as e:
            self.logger.error(f"Error indexing document chunk: {str(e)}")
            raise SearchServiceError(f"Failed to index document chunk: {str(e)}")

    async def index_document_chunks(
        self,
        project_id: str,
        document_id: str,
        document_name: str,
        chunks: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Index multiple document chunks in batch.

        Args:
            project_id: Project identifier
            document_id: Document identifier
            document_name: Name of the document
            chunks: List of chunk data
            metadata: Additional metadata

        Returns:
            bool: True if successful
        """
        try:
            if not self.search_client:
                await self.initialize_index()

            search_documents = []

            for i, chunk_data in enumerate(chunks):
                content = chunk_data.get('content', '')
                content_vector = await self._generate_embedding(content)

                search_document = {
                    "id": f"{document_id}_chunk_{i}",
                    "project_id": project_id,
                    "document_id": document_id,
                    "document_name": document_name,
                    "file_type": metadata.get('file_type', 'unknown') if metadata else 'unknown',
                    "content": content,
                    "chunk_id": chunk_data.get('chunk_id', f'chunk_{i}'),
                    "chunk_index": i,
                    "chunk_size": len(content),
                    "summary": chunk_data.get('summary', ''),
                    "classification": chunk_data.get('classification', ''),
                    "content_type": chunk_data.get('content_type', ''),
                    "keywords": chunk_data.get('keywords', []),
                    "language": chunk_data.get('language', 'en'),
                    "confidence_score": chunk_data.get('confidence_score', 0.0),
                    "content_vector": content_vector,
                    "created_at": datetime.utcnow().isoformat(),
                    "updated_at": datetime.utcnow().isoformat(),
                    "additional_metadata": json.dumps(metadata or {})
                }
                search_documents.append(search_document)

            # Batch upload
            results = self.search_client.upload_documents(search_documents)

            successful_count = sum(1 for result in results if result.succeeded)
            total_count = len(results)

            if successful_count == total_count:
                self.logger.info(f"Successfully indexed {successful_count}/{total_count} chunks for document {document_id}")
                return True
            else:
                self.logger.warning(f"Indexed {successful_count}/{total_count} chunks for document {document_id}")
                return False

        except Exception as e:
            self.logger.error(f"Error indexing document chunks: {str(e)}")
            raise SearchServiceError(f"Failed to index document chunks: {str(e)}")

    async def search_documents(
        self,
        query: str,
        project_id: Optional[str] = None,
        document_types: Optional[List[str]] = None,
        top: int = 10,
        use_semantic_search: bool = True,
        use_vector_search: bool = True
    ) -> Dict[str, Any]:
        """
        Search documents with hybrid approach (text + vector + semantic).

        Args:
            query: Search query
            project_id: Filter by project ID
            document_types: Filter by document types
            top: Number of results to return
            use_semantic_search: Enable semantic search
            use_vector_search: Enable vector search

        Returns:
            Dictionary containing search results and metadata
        """
        try:
            if not self.search_client:
                await self.initialize_index()

            # Build filter conditions
            filters = []
            if project_id:
                filters.append(f"project_id eq '{project_id}'")
            if document_types:
                type_filters = " or ".join([f"file_type eq '{dt}'" for dt in document_types])
                filters.append(f"({type_filters})")

            filter_expression = " and ".join(filters) if filters else None

            search_params = {
                "search_text": query,
                "filter": filter_expression,
                "top": top,
                "include_total_count": True,
                "query_type": "semantic" if use_semantic_search else "simple",
                "semantic_configuration_name": "giani-semantic-config" if use_semantic_search else None
            }

            # Add vector search if enabled
            if use_vector_search:
                query_vector = await self._generate_embedding(query)
                vector_query = VectorizedQuery(
                    vector=query_vector,
                    k_nearest_neighbors=top,
                    fields="content_vector"
                )
                search_params["vector_queries"] = [vector_query]

            # Perform search
            results = self.search_client.search(**search_params)

            # Process results
            documents = []
            for result in results:
                doc = {
                    "id": result.get("id"),
                    "project_id": result.get("project_id"),
                    "document_id": result.get("document_id"),
                    "document_name": result.get("document_name"),
                    "content": result.get("content"),
                    "summary": result.get("summary"),
                    "classification": result.get("classification"),
                    "keywords": result.get("keywords", []),
                    "score": result.get("@search.score", 0),
                    "reranker_score": result.get("@search.reranker_score"),
                    "highlights": result.get("@search.highlights", {}),
                    "chunk_index": result.get("chunk_index"),
                    "created_at": result.get("created_at")
                }
                documents.append(doc)

            return {
                "documents": documents,
                "total_count": getattr(results, 'total_count', len(documents)),
                "query": query,
                "filters_applied": filter_expression,
                "semantic_search_used": use_semantic_search,
                "vector_search_used": use_vector_search
            }

        except Exception as e:
            self.logger.error(f"Error searching documents: {str(e)}")
            raise SearchServiceError(f"Document search failed: {str(e)}")

    async def delete_document(self, document_id: str) -> bool:
        """
        Delete all chunks for a specific document.

        Args:
            document_id: Document identifier

        Returns:
            bool: True if successful
        """
        try:
            if not self.search_client:
                await self.initialize_index()

            # Search for all chunks of the document
            results = self.search_client.search(
                search_text="*",
                filter=f"document_id eq '{document_id}'",
                select=["id"]
            )

            # Collect document IDs to delete
            docs_to_delete = [{"id": result["id"]} for result in results]

            if docs_to_delete:
                # Delete documents
                delete_results = self.search_client.delete_documents(docs_to_delete)
                successful_deletes = sum(1 for result in delete_results if result.succeeded)

                self.logger.info(f"Deleted {successful_deletes}/{len(docs_to_delete)} chunks for document {document_id}")
                return successful_deletes == len(docs_to_delete)

            return True

        except Exception as e:
            self.logger.error(f"Error deleting document: {str(e)}")
            raise SearchServiceError(f"Failed to delete document: {str(e)}")

    async def delete_project_documents(self, project_id: str) -> bool:
        """
        Delete all documents for a specific project.

        Args:
            project_id: Project identifier

        Returns:
            bool: True if successful
        """
        try:
            if not self.search_client:
                await self.initialize_index()

            # Search for all documents in the project
            results = self.search_client.search(
                search_text="*",
                filter=f"project_id eq '{project_id}'",
                select=["id"]
            )

            # Collect document IDs to delete
            docs_to_delete = [{"id": result["id"]} for result in results]

            if docs_to_delete:
                # Delete in batches (Azure Search has batch size limits)
                batch_size = 1000
                total_deleted = 0

                for i in range(0, len(docs_to_delete), batch_size):
                    batch = docs_to_delete[i:i + batch_size]
                    delete_results = self.search_client.delete_documents(batch)
                    total_deleted += sum(1 for result in delete_results if result.succeeded)

                self.logger.info(f"Deleted {total_deleted}/{len(docs_to_delete)} documents for project {project_id}")
                return total_deleted == len(docs_to_delete)

            return True

        except Exception as e:
            self.logger.error(f"Error deleting project documents: {str(e)}")
            raise SearchServiceError(f"Failed to delete project documents: {str(e)}")

    async def get_document_stats(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get statistics about indexed documents.

        Args:
            project_id: Optional project ID to filter by

        Returns:
            Dictionary with statistics
        """
        try:
            if not self.search_client:
                await self.initialize_index()

            filter_expr = f"project_id eq '{project_id}'" if project_id else None

            # Get document count
            results = self.search_client.search(
                search_text="*",
                filter=filter_expr,
                include_total_count=True,
                top=0
            )

            total_chunks = getattr(results, 'total_count', 0)

            # Get document type distribution
            facet_results = self.search_client.search(
                search_text="*",
                filter=filter_expr,
                facets=["file_type"],
                top=0
            )

            file_types = {}
            if hasattr(facet_results, 'facets') and 'file_type' in facet_results.facets:
                for facet in facet_results.facets['file_type']:
                    file_types[facet['value']] = facet['count']

            return {
                "total_chunks": total_chunks,
                "file_type_distribution": file_types,
                "project_id": project_id
            }

        except Exception as e:
            self.logger.error(f"Error getting document stats: {str(e)}")
            raise SearchServiceError(f"Failed to get document stats: {str(e)}")

    async def _generate_embedding(self, text: str) -> List[float]:
        """
        Generate embedding for text using Gemini AI.

        Args:
            text: Text to embed

        Returns:
            List of floats representing the embedding
        """
        try:
            # Use Gemini client to generate embeddings
            # This would need to be implemented based on your Gemini client
            # For now, returning a placeholder
            # You may want to use a different embedding service like OpenAI or Azure OpenAI

            # Placeholder implementation - replace with actual embedding generation
            import numpy as np
            np.random.seed(hash(text) % 2**32)
            return np.random.rand(self.vector_dimension).tolist()

        except Exception as e:
            self.logger.error(f"Error generating embedding: {str(e)}")
            # Return zero vector as fallback
            return [0.0] * self.vector_dimension

    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on the Azure Search service.

        Returns:
            Dictionary with health status
        """
        try:
            if not self.search_client:
                await self.initialize_index()

            # Try to get index statistics
            stats = await self.get_document_stats()

            return {
                "status": "healthy",
                "service_url": self.service_url,
                "index_name": self.index_name,
                "document_count": stats.get("total_chunks", 0),
                "timestamp": datetime.utcnow().isoformat()
            }

        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }