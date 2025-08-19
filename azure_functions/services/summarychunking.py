"""
Summary Chunking Service for converting AI-generated summaries into specialized chunks for RAG.
"""

import logging
import uuid
from typing import Dict, List, Any, Optional
from datetime import datetime

from azure_functions.utils.constants import DocumentGroup, CATEGORY_TO_GROUP_MAPPING

class SummaryChunkingService:
    """
    Service for chunking AI-generated summary JSON into specialized text chunks
    optimized for different types of RAG queries.
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def get_document_group_from_category(self, category: str) -> DocumentGroup:
        """Get document group from category."""
        return CATEGORY_TO_GROUP_MAPPING.get(category, DocumentGroup.GROUP_D)

    def create_chunk_metadata(self, 
                            document_id: str,
                            project_id: str,
                            data_type: str,
                            source_document: Dict[str, Any],
                            chunk_index: int) -> Dict[str, Any]:
        """Create standardized metadata for derived chunks."""
        return {
            "chunk_id": str(uuid.uuid4()),
            "document_id": document_id,
            "project_id": project_id,
            "data_type": data_type,  # e.g., 'derived_summary', 'derived_faq', etc.
            "chunk_index": chunk_index,
            "source_type": "ai_generated_summary",
            "parent_document_filename": source_document.get("document_filename", ""),
            "parent_document_category": source_document.get("document_category", ""),
            "document_group": source_document.get("document_group", ""),
            "created_timestamp": datetime.utcnow().isoformat() + "Z",
            "processing_method": "summary_derived_chunking"
        }

    def create_overall_summary_chunk(self, 
                                   summary_json: Dict[str, Any],
                                   document_id: str,
                                   project_id: str,
                                   chunk_index: int) -> Dict[str, Any]:
        """
        Create the Overall Summary chunk containing key themes, narrative summary, and takeaways.
        This chunk catches broad, thematic, and summary-oriented user queries.
        """
        try:
            # Extract document title
            doc_title = summary_json.get("extracted_metadata", {}).get(
                "universal_metadata", {}
            ).get("suggested_document_title", "Untitled Document")

            # Extract key themes
            themes_list = summary_json.get("ai_overall_key_themes_list", [])
            themes_text = ", ".join([
                theme.get("theme", "") for theme in themes_list if theme.get("theme")
            ])

            # Extract narrative summary
            narrative_summary = summary_json.get("ai_high_level_narrative_summary", {})
            if isinstance(narrative_summary, str):
                summary_text = narrative_summary
            else:
                summary_text = narrative_summary.get("text", "")

            # Extract key takeaways
            takeaways_list = summary_json.get("ai_key_takeaways_bullets", [])
            takeaways_text = " | ".join([
                takeaway.get("text", "") for takeaway in takeaways_list if takeaway.get("text")
            ])

            chunk_text = f"""[DOCUMENT_TITLE] {doc_title}
[KEY_THEMES] {themes_text}
[SUMMARY] {summary_text}
[KEY_TAKEAWAYS] {takeaways_text}"""

            metadata = self.create_chunk_metadata(
                document_id, project_id, "derived_summary", summary_json, chunk_index
            )

            return {
                "text": chunk_text.strip(),
                "metadata": metadata,
                "chunk_type": "overall_summary"
            }

        except Exception as e:
            self.logger.error(f"Failed to create overall summary chunk: {e}")
            raise

    def create_faq_chunk(self, 
                        summary_json: Dict[str, Any],
                        document_id: str,
                        project_id: str,
                        chunk_index: int) -> Dict[str, Any]:
        """
        Create the FAQ chunk containing AI-generated potential questions.
        This acts as a 'honeypot' for user queries.
        """
        try:
            questions_list = summary_json.get("extracted_metadata", {}).get(
                "rag_specific_metadata", {}
            ).get("ai_generated_potential_questions_list", [])

            questions_text = " | ".join([
                q.get("question", "") for q in questions_list if q.get("question")
            ])

            chunk_text = f"[POTENTIAL_QUESTIONS] {questions_text}"

            metadata = self.create_chunk_metadata(
                document_id, project_id, "derived_faq", summary_json, chunk_index
            )

            return {
                "text": chunk_text.strip(),
                "metadata": metadata,
                "chunk_type": "faq"
            }

        except Exception as e:
            self.logger.error(f"Failed to create FAQ chunk: {e}")
            raise

    def create_entities_chunk(self, 
                            summary_json: Dict[str, Any],
                            document_id: str,
                            project_id: str,
                            chunk_index: int) -> Dict[str, Any]:
        """
        Create the Entities chunk containing key entities and their context.
        Optimized for queries about specific people, companies, or concepts.
        """
        try:
            entities_list = summary_json.get("extracted_metadata", {}).get(
                "rag_specific_metadata", {}
            ).get("key_entities_with_context_list", [])

            entities_text = " | ".join([
                f"[{e.get('entity_type', 'ENTITY').upper()}] {e.get('entity', '')}: {e.get('context', '')}"
                for e in entities_list if e.get('entity')
            ])

            chunk_text = f"[KEY_ENTITIES] {entities_text}"

            metadata = self.create_chunk_metadata(
                document_id, project_id, "derived_entities", summary_json, chunk_index
            )

            return {
                "text": chunk_text.strip(),
                "metadata": metadata,
                "chunk_type": "entities"
            }

        except Exception as e:
            self.logger.error(f"Failed to create entities chunk: {e}")
            raise

    def create_data_findings_chunk(self, 
                                 summary_json: Dict[str, Any],
                                 document_id: str,
                                 project_id: str,
                                 chunk_index: int) -> Dict[str, Any]:
        """
        Create Key Data & Findings chunk for Group A & B documents.
        Dense collection of critical data, findings, and recommendations.
        """
        try:
            # Extract key findings from intelligence layer
            findings_list = summary_json.get("extracted_metadata", {}).get(
                "intelligence_layer", {}
            ).get("key_findings_and_data", [])
            findings_text = [f.get("finding", "") for f in findings_list if f.get("finding")]

            # Extract recommendations (Group A specific)
            recommendations_list = summary_json.get("extracted_metadata", {}).get(
                "group_specific", {}
            ).get("key_recommendations_or_proposals_list", [])
            recommendations_text = [r.get("text", "") for r in recommendations_list if r.get("text")]

            # Extract key data points
            data_points_list = summary_json.get("extracted_metadata", {}).get(
                "rag_specific_metadata", {}
            ).get("key_data_points_or_statistics_list", [])
            data_points_text = [
                f"{dp.get('label', '')}: {dp.get('value_text', '')}"
                for dp in data_points_list if dp.get('label') and dp.get('value_text')
            ]

            # Combine all findings and recommendations
            all_findings = findings_text + recommendations_text
            findings_combined = " | ".join(all_findings) if all_findings else ""
            data_combined = " | ".join(data_points_text) if data_points_text else ""

            chunk_text = f"""[KEY_FINDINGS_RECOMMENDATIONS] {findings_combined}
[KEY_DATA_POINTS] {data_combined}"""

            metadata = self.create_chunk_metadata(
                document_id, project_id, "derived_data_findings", summary_json, chunk_index
            )

            return {
                "text": chunk_text.strip(),
                "metadata": metadata,
                "chunk_type": "data_findings"
            }

        except Exception as e:
            self.logger.error(f"Failed to create data findings chunk: {e}")
            raise

    def create_actions_risks_chunk(self, 
                                 summary_json: Dict[str, Any],
                                 document_id: str,
                                 project_id: str,
                                 chunk_index: int) -> Dict[str, Any]:
        """
        Create Actions, Decisions & Risks chunk for Group C & D documents.
        Dense collection of forward-looking and critical items.
        """
        try:
            group_specific = summary_json.get("extracted_metadata", {}).get("group_specific", {})

            # Extract decisions (Group D specific)
            decisions_list = group_specific.get("key_decisions_made_list_of_objects", [])
            decisions_text = [d.get("decision", "") for d in decisions_list if d.get("decision")]

            # Extract action items (Group D specific)
            actions_list = group_specific.get("distinct_action_items_list_of_objects", [])
            actions_text = [a.get("action", "") for a in actions_list if a.get("action")]

            # Extract risks (Group C specific)
            risks_list = group_specific.get("key_risks_issues_status_list_of_objects", [])
            risks_text = [r.get("risk", "") for r in risks_list if r.get("risk")]

            # Extract execution items from intelligence layer
            execution_list = summary_json.get("extracted_metadata", {}).get(
                "intelligence_layer", {}
            ).get("execution_and_actions", [])
            execution_text = [e.get("action", "") for e in execution_list if e.get("action")]

            # Combine all action-oriented content
            all_decisions = " | ".join(decisions_text) if decisions_text else ""
            all_actions = " | ".join(actions_text + execution_text) if (actions_text + execution_text) else ""
            all_risks = " | ".join(risks_text) if risks_text else ""

            chunk_text = f"""[KEY_DECISIONS] {all_decisions}
[KEY_ACTIONS] {all_actions}
[KEY_RISKS] {all_risks}"""

            metadata = self.create_chunk_metadata(
                document_id, project_id, "derived_actions_risks", summary_json, chunk_index
            )

            return {
                "text": chunk_text.strip(),
                "metadata": metadata,
                "chunk_type": "actions_risks"
            }

        except Exception as e:
            self.logger.error(f"Failed to create actions risks chunk: {e}")
            raise

    def create_derived_chunks(self, 
                            summary_json: Dict[str, Any],
                            document_id: str,
                            project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Create all derived chunks from AI-generated summary JSON.
        
        Args:
            summary_json: The complete AI-generated summary JSON object
            document_id: The document ID
            project_id: The project ID (optional)
            
        Returns:
            List of derived chunk dictionaries ready for vectorization
        """
        self.logger.info(f"Creating derived chunks for document: {document_id}")
        
        if not project_id:
            project_id = "default_project"
        
        chunks = []
        chunk_index = 0

        try:
            # Get document group for adaptive chunking
            document_category = summary_json.get("document_category", "")
            document_group = self.get_document_group_from_category(document_category)
            
            self.logger.debug(f"Document category: {document_category}, Group: {document_group.value}")

            # Universal chunks (created for all document groups)
            
            # 1. Overall Summary chunk
            overall_summary_chunk = self.create_overall_summary_chunk(
                summary_json, document_id, project_id, chunk_index
            )
            chunks.append(overall_summary_chunk)
            chunk_index += 1

            # 2. FAQ chunk
            faq_chunk = self.create_faq_chunk(
                summary_json, document_id, project_id, chunk_index
            )
            chunks.append(faq_chunk)
            chunk_index += 1

            # 3. Entities chunk
            entities_chunk = self.create_entities_chunk(
                summary_json, document_id, project_id, chunk_index
            )
            chunks.append(entities_chunk)
            chunk_index += 1

            # Group-specific chunks
            if document_group in [DocumentGroup.GROUP_A, DocumentGroup.GROUP_B]:
                # Strategic & Research docs: Key Data & Findings chunk
                data_findings_chunk = self.create_data_findings_chunk(
                    summary_json, document_id, project_id, chunk_index
                )
                chunks.append(data_findings_chunk)
                chunk_index += 1
                
            elif document_group in [DocumentGroup.GROUP_C, DocumentGroup.GROUP_D]:
                # Execution & Conversational docs: Actions, Decisions & Risks chunk
                actions_risks_chunk = self.create_actions_risks_chunk(
                    summary_json, document_id, project_id, chunk_index
                )
                chunks.append(actions_risks_chunk)
                chunk_index += 1

            # Filter out chunks with empty or very short text
            valid_chunks = []
            for chunk in chunks:
                chunk_text = chunk.get("text", "").strip()
                if len(chunk_text) > 20:  # Minimum meaningful chunk size
                    valid_chunks.append(chunk)
                else:
                    self.logger.debug(f"Filtered out short chunk of type: {chunk.get('chunk_type')}")

            self.logger.info(f"Created {len(valid_chunks)} valid derived chunks for document: {document_id}")
            return valid_chunks

        except Exception as e:
            self.logger.error(f"Failed to create derived chunks for document {document_id}: {e}")
            raise

    def chunk_multiple_summaries(self, summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Process multiple summary JSON objects and create derived chunks for all.
        
        Args:
            summaries: List of AI-generated summary JSON objects
            
        Returns:
            List of all derived chunks from all summaries
        """
        self.logger.info(f"Processing {len(summaries)} summaries for chunking")
        
        all_chunks = []
        
        for i, summary in enumerate(summaries):
            try:
                document_id = summary.get("document_id", f"doc_{i}")
                project_id = summary.get("project_id", "default_project")
                
                chunks = self.create_derived_chunks(summary, document_id, project_id)
                all_chunks.extend(chunks)
                
            except Exception as e:
                self.logger.error(f"Failed to process summary {i}: {e}")
                continue

        self.logger.info(f"Created total of {len(all_chunks)} derived chunks from {len(summaries)} summaries")
        return all_chunks

    def get_chunk_statistics(self, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Get statistics about the generated chunks."""
        if not chunks:
            return {"total_chunks": 0}

        chunk_types = {}
        total_text_length = 0
        
        for chunk in chunks:
            chunk_type = chunk.get("chunk_type", "unknown")
            chunk_types[chunk_type] = chunk_types.get(chunk_type, 0) + 1
            total_text_length += len(chunk.get("text", ""))

        return {
            "total_chunks": len(chunks),
            "chunk_types": chunk_types,
            "average_chunk_length": total_text_length / len(chunks) if chunks else 0,
            "total_text_length": total_text_length
        }
