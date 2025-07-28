#!/usr/bin/env python3
"""
Test script to verify database setup and SQLAlchemy integration.
"""
import os
import sys
import logging

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_database_setup():
    """Test the database setup and basic operations."""
    try:
        # Test database initialization
        from giani_pkb.core.database_init import init_database
        logger.info("Testing database initialization...")
        init_database()

        # Test database service
        from giani_pkb.utils.database import SessionLocal
        from giani_pkb.core.services.database_service import DatabaseService

        db = SessionLocal()
        db_service = DatabaseService(db)

        # Test user creation
        logger.info("Testing user creation...")
        user = db_service.create_user(
            username="test_user",
            email="test@example.com",
            hashed_password="test_password_hash"
        )
        logger.info(f"Created user: {user.username} with ID: {user.id}")

        # Test project creation
        logger.info("Testing project creation...")
        project = db_service.create_project(
            name="Test Project",
            owner_id=user.id,
            description="A test project"
        )
        logger.info(f"Created project: {project.name} with ID: {project.id}")

        # Test document creation
        logger.info("Testing document creation...")
        document = db_service.create_document(
            original_filename="test_document.pdf",
            file_size=1024,
            file_mime_type="application/pdf",
            storage_path="/path/to/test_document.pdf",
            category_folder="documents",
            source="doc_source",
            stored_filename="test_metadata.json",
            final_category="1. Strategy Document/Deck",
            final_purpose="Test document for database verification",
            priority="Medium",
            user_id=user.id,
            project_id=project.id
        )
        logger.info(f"Created document: {document.original_filename} with ID: {document.id}")

        # Test document retrieval
        logger.info("Testing document retrieval...")
        retrieved_doc = db_service.get_document_by_id(document.id)
        if retrieved_doc:
            logger.info(f"Retrieved document: {retrieved_doc.original_filename}")

        # Test document search
        logger.info("Testing document search...")
        search_results = db_service.search_documents("test")
        logger.info(f"Found {len(search_results)} documents matching 'test'")

        # Test statistics
        logger.info("Testing statistics...")
        stats = db_service.get_document_statistics()
        logger.info(f"Database statistics: {stats}")

        # Clean up test data
        logger.info("Cleaning up test data...")
        db_service.delete_document(document.id)
        db_service.delete_project(project.id)
        db_service.delete_user(user.id)

        db.close()
        logger.info("✅ All database tests passed successfully!")

    except Exception as e:
        logger.error(f"❌ Database test failed: {e}")
        raise

def test_services():
    """Test the refactored services."""
    try:
        logger.info("Testing refactored services...")

        # Test classification service
        from giani_pkb.core.services.classification import ClassificationService
        classifier = ClassificationService()
        logger.info("✅ ClassificationService imported successfully")

        # Test summarization service
        from giani_pkb.core.services.summarization import SummarizationService
        summarizer = SummarizationService()
        logger.info("✅ SummarizationService imported successfully")

        # Test metadata manager service
        from giani_pkb.core.services.metadata_manager import MetadataManagerService
        metadata_manager = MetadataManagerService()
        logger.info("✅ MetadataManagerService imported successfully")

        logger.info("✅ All services imported successfully!")

    except Exception as e:
        logger.error(f"❌ Service test failed: {e}")
        raise

def test_utilities():
    """Test the utility modules."""
    try:
        logger.info("Testing utility modules...")

        # Test API tracker
        from giani_pkb.utils.api_tracker import APICallTracker
        tracker = APICallTracker()
        tracker.log_api_call(
            prompt="Test prompt",
            response="Test response",
            model="test-model",
            timestamp="2024-01-01T00:00:00Z"
        )
        logger.info("✅ APICallTracker working")

        # Test prompt generators
        from giani_pkb.utils.prompt_generators import get_group_a_prompt
        prompt = get_group_a_prompt(
            originalFilename="test.pdf",
            documentSourceType="Strategy Document",
            userNoteOnPurpose="Test purpose",
            key_document_chunks="Test content"
        )
        logger.info("✅ Prompt generators working")

        # Test classification utils
        from giani_pkb.utils.classification_utils import fallback_classification
        classification, purpose = fallback_classification("strategy_document.pdf")
        logger.info(f"✅ Fallback classification: {classification}")

        logger.info("✅ All utilities working correctly!")

    except Exception as e:
        logger.error(f"❌ Utility test failed: {e}")
        raise

if __name__ == "__main__":
    logger.info("🚀 Starting Giani AI refactored codebase tests...")

    try:
        test_database_setup()
        test_services()
        test_utilities()

        logger.info("🎉 All tests completed successfully!")
        logger.info("The refactored codebase is working correctly!")

    except Exception as e:
        logger.error(f"💥 Test suite failed: {e}")
        sys.exit(1)