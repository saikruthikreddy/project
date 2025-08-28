"""
Azure AI Search Service Module for Giani AI Project Knowledge Base

This module provides integration with Azure AI Search for document indexing,
searching, and retrieval with semantic capabilities.
"""

import os
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
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
    VectorSearch,
    HnswAlgorithmConfiguration,
    VectorSearchProfile,
    SemanticConfiguration,
    SemanticSearch,
    SemanticPrioritizedFields,
    SemanticField,
)
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ResourceNotFoundError

from ..utils.config import Config
from ..utils.exceptions import SearchServiceError
from ..utils.gemini_client import initialize_gemini_client
from .rag.embed_chunks import create_embeddings_with_retry

VECTOR_PROFILE_NAME = "giani-doc-chunks-vector"
SEMANTIC_CONFIG_NAME = "giani-doc-chunks-semantic-config"

class AzureSearchService:
    """
    Azure AI Search service for document indexing and retrieval.
    Integrates with the existing Giani AI project structure.
    """

    def __init__(self):
        self.config = Config()
        self.logger = logging.getLogger(__name__)

        # Azure Search configuration
        self.service_name = os.getenv('AZURE_SEARCH_SERVICE_NAME')
        self.service_url = os.getenv('AZURE_SEARCH_SERVICE_URL')
        self.api_key = os.getenv('AZURE_SEARCH_API_KEY')

        if not all([self.service_name, self.service_url, self.api_key]):
            raise SearchServiceError("Missing Azure Search configuration in environment variables")

        self.credential = AzureKeyCredential(self.api_key)
        self.index_client = SearchIndexClient(
            endpoint=self.service_url,
            credential=self.credential
        )

        self.index_name = "giani-doc-chunks-index"
        self.vector_dimension = 1536
        initialize_gemini_client()
        self.search_client = None

    async def initialize_index(self) -> bool:
        """
        Initialize the search index with proper schema.
        """
        try:
            try:
                _ = self.index_client.get_index(self.index_name)
                self.logger.info(f"Index '{self.index_name}' already exists")
                self._initialize_search_client()
                return True
            except ResourceNotFoundError:
                pass

            index = self._create_index_schema()
            self.index_client.create_index(index)
            self.logger.info(f"Created new index: {self.index_name}")
            self._initialize_search_client()
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize index: {str(e)}")
            raise SearchServiceError(f"Index initialization failed: {str(e)}")

    def _initialize_search_client(self):
        self.search_client = SearchClient(
            endpoint=self.service_url,
            index_name=self.index_name,
            credential=self.credential
        )

    def _create_index_schema(self) -> SearchIndex:
        # Adapted schema: every filterable/searchable/retrievable field explicit
        fields = [
            # Identity & governance
            SimpleField(name="id", type=SearchFieldDataType.String, key=True, retrievable=True),
            SimpleField(name="project_id", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="document_id", type=SearchFieldDataType.String, filterable=True),

            # Chunk structure & metadata
            SimpleField(name="chunk_id", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="chunk_type", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="chunk_index", type=SearchFieldDataType.Int32, filterable=True, sortable=True, retrievable=True),
            SimpleField(name="slide_number", type=SearchFieldDataType.Int32, filterable=True, sortable=True, retrievable=True),
            SimpleField(name="same_table_group_id", type=SearchFieldDataType.String, filterable=True, retrievable=True),
            SimpleField(name="source_page_numbers", type=SearchFieldDataType.Collection(SearchFieldDataType.Int32), filterable=True),
            SimpleField(name="speaker_attribution", type=SearchFieldDataType.String, filterable=True, retrievable=True),
            SimpleField(name="previous_chunk_id", type=SearchFieldDataType.String, filterable=True, retrievable=True),
            SimpleField(name="slide_context_id", type=SearchFieldDataType.String, filterable=True, retrievable=True),
            SimpleField(name="semantic_similarity_score", type=SearchFieldDataType.Double, filterable=True, sortable=True, retrievable=True),
            SimpleField(name="role", type=SearchFieldDataType.String, filterable=True, retrievable=True),
            SimpleField(name="element_type", type=SearchFieldDataType.String, filterable=True, retrievable=True),
            SimpleField(name="region_type", type=SearchFieldDataType.String, filterable=True, retrievable=True),
            SimpleField(name="subtype", type=SearchFieldDataType.String, filterable=True, retrievable=True),
            SimpleField(name="caption", type=SearchFieldDataType.String, searchable=True, retrievable=True),
            SimpleField(name="section", type=SearchFieldDataType.String, searchable=True, retrievable=True),
            SimpleField(name="column_names", type=SearchFieldDataType.Collection(SearchFieldDataType.String), retrievable=True),
            SimpleField(name="slide_range", type=SearchFieldDataType.Collection(SearchFieldDataType.Int32), filterable=True, retrievable=True),
            SimpleField(name="bbox", type=SearchFieldDataType.String, retrievable=True),  # as JSON/CSV
            SimpleField(name="label_bbox", type=SearchFieldDataType.String, retrievable=True),  # as JSON/CSV
            SimpleField(name="structural_metadata_raw", type=SearchFieldDataType.String, retrievable=True),

            # Content
            SearchableField(name="text", type=SearchFieldDataType.String, searchable=True, analyzer_name="en.lucene"),

            # Embedding vector
            SearchField(
                name="vector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                retrievable=False,
                filterable=False,
                sortable=False,
                facetable=False,
                synonym_map_names=None,
                vector_search_dimensions=self.vector_dimension,
                vector_search_profile_name=VECTOR_PROFILE_NAME
            ),

            # Chunk provenance
            SimpleField(name="embedding_model", type=SearchFieldDataType.String, retrievable=True),
            SimpleField(name="embedding_checksum", type=SearchFieldDataType.String, retrievable=True),

            # Timestamps
            SimpleField(name="created_at", type=SearchFieldDataType.DateTimeOffset, filterable=True, sortable=True),
            SimpleField(name="updated_at", type=SearchFieldDataType.DateTimeOffset, filterable=True, sortable=True),
        ]

        vector_search = VectorSearch(
            algorithms=[
                HnswAlgorithmConfiguration(
                    name="hnsw-chunk-algorithm",
                    parameters={
                        "m": 20,
                        "efConstruction": 300,
                        "efSearch": 80,
                        "metric": "cosine"
                    },
                )
            ],
            profiles=[
                VectorSearchProfile(
                    name=VECTOR_PROFILE_NAME,
                    algorithm_configuration_name="hnsw-chunk-algorithm"
                )
            ],
        )

        semantic_config = SemanticConfiguration(
            name=SEMANTIC_CONFIG_NAME,
            prioritized_fields=SemanticPrioritizedFields(
                title_field=SemanticField(field_name="section"),
                content_fields=[
                    SemanticField(field_name="text"),
                    SemanticField(field_name="caption")
                ],
                keyword_fields=[
                    SemanticField(field_name="chunk_type"),
                    SemanticField(field_name="section")
                ]
            )
        )

        semantic_search = SemanticSearch(configurations=[semantic_config])

        return SearchIndex(
            name=self.index_name,
            fields=fields,
            vector_search=vector_search,
            semantic_search=semantic_search
        )

    @staticmethod
    def map_search_result_to_chunk(record: dict) -> dict:
        # Maps every field, robustly, for deserialized result
        return {
            "id": record.get("id"),
            "project_id": record.get("project_id"),
            "document_id": record.get("document_id"),
            "chunk_id": record.get("chunk_id"),
            "chunk_type": record.get("chunk_type"),
            "chunk_index": record.get("chunk_index"),
            "slide_number": record.get("slide_number"),
            "same_table_group_id": record.get("same_table_group_id"),
            "source_page_numbers": record.get("source_page_numbers", []),
            "speaker_attribution": record.get("speaker_attribution"),
            "previous_chunk_id": record.get("previous_chunk_id"),
            "slide_context_id": record.get("slide_context_id"),
            "semantic_similarity_score": record.get("semantic_similarity_score"),
            "role": record.get("role"),
            "element_type": record.get("element_type"),
            "region_type": record.get("region_type"),
            "subtype": record.get("subtype"),
            "caption": record.get("caption"),
            "section": record.get("section"),
            "column_names": record.get("column_names", []),
            "slide_range": record.get("slide_range", []),
            "bbox": record.get("bbox"),
            "label_bbox": record.get("label_bbox"),
            "structural_metadata_raw": record.get("structural_metadata_raw"),
            "text": record.get("text"),
            "embedding_model": record.get("embedding_model"),
            "embedding_checksum": record.get("embedding_checksum"),
            "created_at": record.get("created_at"),
            "updated_at": record.get("updated_at"),
            "score": record.get("@search.score"),
            "highlights": record.get("@search.highlights", {}),
        }

    async def index_document_chunk(
        self,
        project_id: str,
        document_id: str,
        document_name: str,
        chunk_data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Index a single document chunk with full field support.
        """
        try:
            if not self.search_client:
                await self.initialize_index()

            now = datetime.utcnow().isoformat()
            search_document = {
                "id": str(uuid.uuid4()),
                "project_id": project_id,
                "document_id": document_id,
                "chunk_id": chunk_data.get("chunk_id", ""),
                "chunk_type": chunk_data.get("chunk_type", ""),
                "chunk_index": chunk_data.get("chunk_index", 0),
                "slide_number": chunk_data.get("slide_number"),
                "same_table_group_id": chunk_data.get("same_table_group_id"),
                "source_page_numbers": chunk_data.get("source_page_numbers", []),
                "speaker_attribution": chunk_data.get("speaker_attribution"),
                "previous_chunk_id": chunk_data.get("previous_chunk_id"),
                "slide_context_id": chunk_data.get("slide_context_id"),
                "semantic_similarity_score": chunk_data.get("semantic_similarity_score"),
                "role": chunk_data.get("role"),
                "element_type": chunk_data.get("element_type"),
                "region_type": chunk_data.get("region_type"),
                "subtype": chunk_data.get("subtype"),
                "caption": chunk_data.get("caption"),
                "section": chunk_data.get("section"),
                "column_names": chunk_data.get("column_names", []),
                "slide_range": chunk_data.get("slide_range", []),
                "bbox": chunk_data.get("bbox"),
                "label_bbox": chunk_data.get("label_bbox"),
                "structural_metadata_raw": json.dumps(chunk_data.get("structural_metadata_raw", {})),
                "text": chunk_data.get("text", ""),
                "embedding_model": chunk_data.get("embedding_model", ""),
                "embedding_checksum": chunk_data.get("embedding_checksum", ""),
                "created_at": now,
                "updated_at": now,
                # Embedding vector
                "vector": chunk_data.get("embedding_vector", []),
            }
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
        """
        try:
            if not self.search_client:
                await self.initialize_index()
            now = datetime.utcnow().isoformat()
            search_documents = []
            for chunk in chunks:
                doc = {
                    "id": str(uuid.uuid4()),
                    "project_id": project_id,
                    "document_id": document_id,
                    "chunk_id": chunk.get("chunk_id", ""),
                    "chunk_type": chunk.get("chunk_type", ""),
                    "chunk_index": chunk.get("chunk_index", 0),
                    "slide_number": chunk.get("slide_number"),
                    "same_table_group_id": chunk.get("same_table_group_id"),
                    "source_page_numbers": chunk.get("source_page_numbers", []),
                    "speaker_attribution": chunk.get("speaker_attribution"),
                    "previous_chunk_id": chunk.get("previous_chunk_id"),
                    "slide_context_id": chunk.get("slide_context_id"),
                    "semantic_similarity_score": chunk.get("semantic_similarity_score"),
                    "role": chunk.get("role"),
                    "element_type": chunk.get("element_type"),
                    "region_type": chunk.get("region_type"),
                    "subtype": chunk.get("subtype"),
                    "caption": chunk.get("caption"),
                    "section": chunk.get("section"),
                    "column_names": chunk.get("column_names", []),
                    "slide_range": chunk.get("slide_range", []),
                    "bbox": chunk.get("bbox"),
                    "label_bbox": chunk.get("label_bbox"),
                    "structural_metadata_raw": json.dumps(chunk.get("structural_metadata_raw", {})),
                    "text": chunk.get("text", ""),
                    "embedding_model": chunk.get("embedding_model", ""),
                    "embedding_checksum": chunk.get("embedding_checksum", ""),
                    "created_at": now,
                    "updated_at": now,
                    #
                    "vector": chunk.get("embedding_vector", []),
                }
                search_documents.append(doc)
            results = self.search_client.upload_documents(search_documents)
            successful = sum(1 for res in results if res.succeeded)
            if successful == len(results):
                self.logger.info(f"Successfully indexed {successful}/{len(results)} chunks for document {document_id}")
                return True
            else:
                self.logger.warning(f"Indexed {successful}/{len(results)} chunks for document {document_id}")
                return False
        except Exception as e:
            self.logger.error(f"Error indexing document chunks: {str(e)}")
            raise SearchServiceError(f"Failed to index document chunks: {str(e)}")

    async def search_documents(
        self,
        query: str,
        project_id: Optional[str] = None,
        chunk_types: Optional[List[str]] = None,
        top: int = 10,
        use_semantic_search: bool = True,
        use_vector_search: bool = True
    ) -> Dict[str, Any]:
        """
        Search documents with hybrid approach (text + vector + semantic).
        """
        try:
            if not self.search_client:
                await self.initialize_index()

            # Build filter conditions
            filters = []
            if project_id:
                filters.append(f"project_id eq '{project_id}'")
            if chunk_types:
                ct_filters = " or ".join([f"chunk_type eq '{t}'" for t in chunk_types])
                filters.append(f"({ct_filters})")
            filter_expression = " and ".join(filters) if filters else None

            search_params = {
                "search_text": query,
                "filter": filter_expression,
                "top": top,
                "include_total_count": True,
                "query_type": "semantic" if use_semantic_search else "simple",
                "semantic_configuration_name": SEMANTIC_CONFIG_NAME if use_semantic_search else None,
            }

            if use_vector_search:
                query_vector = await self._generate_embedding(query)
                vector_query = VectorizedQuery(
                    vector=query_vector,
                    k_nearest_neighbors=top,
                    fields="vector"
                )
                search_params["vector_queries"] = [vector_query]

            results = self.search_client.search(**search_params)
            documents = [self.map_search_result_to_chunk(record) for record in results]
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
        Delete all chunks for a specific document (by document_id).
        """
        try:
            if not self.search_client:
                await self.initialize_index()
            # Search all chunks for the given document ID and collect their search index IDs
            results = self.search_client.search(
                search_text="*",
                filter=f"document_id eq '{document_id}'",
                select=["id"]
            )
            docs_to_delete = [{"id": record["id"]} for record in results]
            if docs_to_delete:
                deleted = self.search_client.delete_documents(docs_to_delete)
                successful = sum(1 for r in deleted if r.succeeded)
                self.logger.info(f"Deleted {successful}/{len(docs_to_delete)} chunks for document {document_id}")
                return successful == len(docs_to_delete)
            return True
        except Exception as e:
            self.logger.error(f"Error deleting document: {str(e)}")
            raise SearchServiceError(f"Failed to delete document: {str(e)}")

    async def delete_project_documents(self, project_id: str) -> bool:
        """
        Delete all chunks for all documents in a specific project.
        """
        try:
            if not self.search_client:
                await self.initialize_index()
            results = self.search_client.search(
                search_text="*",
                filter=f"project_id eq '{project_id}'",
                select=["id"]
            )
            docs_to_delete = [{"id": record["id"]} for record in results]
            if docs_to_delete:
                batch_size = 1000
                total_deleted = 0
                for i in range(0, len(docs_to_delete), batch_size):
                    batch = docs_to_delete[i:i + batch_size]
                    deleted = self.search_client.delete_documents(batch)
                    total_deleted += sum(1 for res in deleted if res.succeeded)
                self.logger.info(f"Deleted {total_deleted}/{len(docs_to_delete)} chunks for project {project_id}")
                return total_deleted == len(docs_to_delete)
            return True
        except Exception as e:
            self.logger.error(f"Error deleting project documents: {str(e)}")
            raise SearchServiceError(f"Failed to delete project documents: {str(e)}")

    async def get_document_stats(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get simple statistics for indexed documents (chunk counts).
        """
        try:
            if not self.search_client:
                await self.initialize_index()
            filter_expr = f"project_id eq '{project_id}'" if project_id else None
            results = self.search_client.search(
                search_text="*",
                filter=filter_expr,
                include_total_count=True,
                top=0
            )
            total_chunks = getattr(results, 'total_count', 0)
            # (Can extend for facets/distributions if needed)
            return {
                "total_chunks": total_chunks,
                "project_id": project_id
            }
        except Exception as e:
            self.logger.error(f"Error getting document stats: {str(e)}")
            raise SearchServiceError(f"Failed to get document stats: {str(e)}")

    async def _generate_embedding(self, text: str) -> List[float]:
        """
        Generate embedding for text using Gemini AI (or OpenAI etc.).
        """
        try:
            # Should return a flat list of floats, length == self.vector_dimension
            embedding = create_embeddings_with_retry([text])
            if isinstance(embedding, list) and len(embedding) == 1:
                return embedding[0]
            return embedding
        except Exception as e:
            self.logger.error(f"Error generating embedding: {str(e)}")
            return [0.0] * self.vector_dimension
