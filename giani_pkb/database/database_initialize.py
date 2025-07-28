"""
Database initialization using SQLAlchemy ORM.
"""
import logging
from sqlalchemy import inspect
from sqlalchemy import text
import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))


from giani_pkb.utils.database import get_db, create_tables, drop_tables, engine
from giani_pkb.models.database_models import User, Project, Document, DocumentChunk, DocumentSummary, APICallLog
from giani_pkb.utils.auth_utils import hash_password

logger = logging.getLogger(__name__)

class DatabaseInitializer:
    """
    Database initialization and management using SQLAlchemy ORM.
    """

    def __init__(self):
        self.engine = engine

    def initialize_database(self, drop_existing: bool = False) -> bool:
        """
        Initialize the database with all required tables.

        Args:
            drop_existing: Whether to drop existing tables before creating new ones

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if drop_existing:
                logger.info("Dropping existing tables...")
                drop_tables()

            logger.info("Creating database tables...")
            create_tables()

            # Verify tables were created
            inspector = inspect(self.engine)
            tables = inspector.get_table_names()

            expected_tables = {
                'users', 'projects', 'documents', 'document_chunks',
                'document_summaries', 'api_call_logs'
            }

            created_tables = set(tables)
            missing_tables = expected_tables - created_tables

            if missing_tables:
                logger.error(f"Missing tables: {missing_tables}")
                return False

            logger.info(f"Database initialized successfully! Created tables: {list(created_tables)}")
            return True

        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            return False

    def create_initial_data(self) -> bool:
        """
        Create initial data for the application (admin user and default project).

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            db = next(get_db())

            # Check if we already have users
            existing_users = db.query(User).count()
            if existing_users > 0:
                logger.info("Database already contains users, skipping initial data creation")
                return True

            # Create a default admin user
            admin_user = User(
                username="admin",
                email="admin@giani.ai",
                hashed_password=hash_password("admin123"),  # Properly hashed password
                is_active=True,
                is_superuser=True
            )
            db.add(admin_user)
            db.flush()  # Get the user ID

            # Create a default project
            default_project = Project(
                name="Default Project",
                description="Default project for initial setup",
                owner_id=admin_user.id,
                is_active=True
            )
            db.add(default_project)

            db.commit()

            logger.info("Created default admin user and project")
            logger.info("Admin credentials: email=admin@giani.ai, password=admin123")
            return True

        except Exception as e:
            logger.error(f"Error creating initial data: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def migrate_from_json_to_database(self) -> bool:
        """
        Migrate data from JSON files to the database.
        This function can be used to migrate existing JSON-based data to SQLAlchemy.

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Try to import the metadata manager (may not exist in new structure)
            try:
                from giani_pkb.services.metadata_manager import MetadataManagerService
                metadata_manager = MetadataManagerService()
                master_metadata = metadata_manager.load_master_metadata()
            except ImportError:
                logger.warning("MetadataManagerService not available, skipping JSON migration")
                return True

            db = next(get_db())

            # Create a default user for migration
            default_user = db.query(User).filter(User.username == "admin").first()
            if not default_user:
                default_user = User(
                    username="admin",
                    email="admin@giani.ai",
                    hashed_password=hash_password("migrated_user"),
                    is_active=True,
                    is_superuser=True
                )
                db.add(default_user)
                db.flush()

            # Create a default project for migration
            default_project = db.query(Project).filter(Project.name == "Migrated Project").first()
            if not default_project:
                default_project = Project(
                    name="Migrated Project",
                    description="Project for migrated data",
                    owner_id=default_user.id,
                    is_active=True
                )
                db.add(default_project)
                db.flush()

            # Migrate documents
            documents_data = master_metadata.get("documents", [])
            migrated_count = 0

            for doc_data in documents_data:
                try:
                    # Convert JSON data to database format
                    document = Document(
                        original_filename=doc_data.get("original_filename", ""),
                        file_size=doc_data.get("file_size", 0),
                        file_mime_type=doc_data.get("file_mime_type", ""),
                        storage_path=doc_data.get("file_path", ""),
                        category_folder=doc_data.get("document_type", ""),
                        stored_filename=doc_data.get("metadata_file_path", ""),
                        final_category=doc_data.get("ai_classification", ""),
                        final_purpose=doc_data.get("document_purpose", ""),
                        priority=doc_data.get("priority", "Medium"),
                        user_id=default_user.id,
                        project_id=default_project.id
                    )
                    db.add(document)
                    migrated_count += 1

                except Exception as e:
                    logger.error(f"Error migrating document {doc_data.get('document_id', 'unknown')}: {e}")
                    continue

            db.commit()
            logger.info(f"Successfully migrated {migrated_count} documents to database")
            return True

        except Exception as e:
            logger.error(f"Migration failed: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def add_sample_data(self, overwrite: bool = False) -> bool:
        """
        Add sample data for testing and development.

        Args:
            overwrite: Whether to overwrite existing sample data

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            db = next(get_db())

            # Check if sample user already exists
            existing_user = db.query(User).filter(User.email == 'test@example.com').first()
            if existing_user and not overwrite:
                logger.info("Sample data already exists. Use overwrite=True to replace.")
                return True

            if existing_user and overwrite:
                # Remove existing sample data
                logger.info("Removing existing sample data...")
                db.query(DocumentSummary).filter(DocumentSummary.document_id.in_(
                    db.query(Document.id).filter(Document.user_id == existing_user.id)
                )).delete()
                db.query(DocumentChunk).filter(DocumentChunk.document_id.in_(
                    db.query(Document.id).filter(Document.user_id == existing_user.id)
                )).delete()
                db.query(Document).filter(Document.user_id == existing_user.id).delete()
                db.query(Project).filter(Project.owner_id == existing_user.id).delete()
                db.delete(existing_user)
                db.commit()

            # Create sample user
            sample_user = User(
                username='testuser',
                email='test@example.com',
                hashed_password=hash_password('password123'),
                is_active=True,
                is_superuser=False
            )
            db.add(sample_user)
            db.flush()  # Get the user ID

            # Create sample project
            sample_project = Project(
                name='Sample Project',
                description='This is a sample project for testing purposes',
                owner_id=sample_user.id,
                is_active=True
            )
            db.add(sample_project)
            db.flush()  # Get the project ID

            # Create sample document
            sample_document = Document(
                original_filename='sample_document.pdf',
                file_size=1024000,  # 1MB
                file_mime_type='application/pdf',
                storage_path='/data/uploaded_documents/formal/sample_document.pdf',
                category_folder='formal',
                stored_filename='sample_document_20240101.pdf',
                final_category='1. Strategy Document/Deck',
                final_purpose='Sample document for testing the system functionality',
                priority='Medium',
                text_preview='This is a sample document content for testing purposes...',
                user_id=sample_user.id,
                project_id=sample_project.id
            )
            db.add(sample_document)
            db.flush()  # Get the document ID

            # Create sample document chunk
            sample_chunk = DocumentChunk(
                chunk_id='sample-chunk-001',
                document_id=sample_document.id,
                chunk_text='This is a sample chunk of document content for testing the chunking functionality.',
                source_page_number=[1],
                structural_metadata={
                    'block_type': 'paragraph',
                    'source_type': 'text',
                    'page_number': 1
                }
            )
            db.add(sample_chunk)

            # Create sample document summary
            sample_summary = DocumentSummary(
                document_id=sample_document.id,
                summary_content='This is a sample document that demonstrates the system functionality.',
                llm_used='gpt-3.5-turbo',
                summary_metadata={
                    'summary_type': 'extractive',
                    'word_count': 15
                }
            )
            db.add(sample_summary)

            # Create sample API call log
            sample_api_log = APICallLog(
                call_number=1,
                model='gpt-3.5-turbo',
                prompt_preview='Summarize the following document...',
                response_preview='This document contains...',
                prompt_length=100,
                response_length=50,
                success=True
            )
            db.add(sample_api_log)

            db.commit()

            logger.info("Sample data added successfully!")
            logger.info("Test credentials: email=test@example.com, password=password123")
            return True

        except Exception as e:
            logger.error(f"Error adding sample data: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def verify_database_integrity(self) -> bool:
        """
        Verify database integrity by checking table structure and relationships.

        Returns:
            bool: True if database is valid, False otherwise
        """
        try:
            db = next(get_db())

            # Check if tables exist and have expected columns
            inspector = inspect(self.engine)

            # Verify User table
            user_columns = {col['name'] for col in inspector.get_columns('users')}
            expected_user_columns = {'id', 'username', 'email', 'hashed_password', 'is_active', 'is_superuser', 'created_at', 'updated_at'}
            if not expected_user_columns.issubset(user_columns):
                logger.error(f"User table missing columns: {expected_user_columns - user_columns}")
                return False

            # Verify Project table
            project_columns = {col['name'] for col in inspector.get_columns('projects')}
            expected_project_columns = {'id', 'name', 'description', 'owner_id', 'is_active', 'created_at', 'updated_at'}
            if not expected_project_columns.issubset(project_columns):
                logger.error(f"Project table missing columns: {expected_project_columns - project_columns}")
                return False

            # Verify Document table
            document_columns = {col['name'] for col in inspector.get_columns('documents')}
            expected_document_columns = {'id', 'original_filename', 'file_size', 'file_mime_type', 'storage_path', 'category_folder', 'stored_filename', 'final_category', 'final_purpose', 'priority', 'text_preview', 'user_id', 'project_id'}
            if not expected_document_columns.issubset(document_columns):
                logger.error(f"Document table missing columns: {expected_document_columns - document_columns}")
                return False

            # Test basic queries
            user_count = db.query(User).count()
            project_count = db.query(Project).count()
            document_count = db.query(Document).count()

            logger.info(f"Database integrity check passed. Records: Users={user_count}, Projects={project_count}, Documents={document_count}")
            return True

        except Exception as e:
            logger.error(f"Database integrity check failed: {e}")
            return False
        finally:
            db.close()

    def get_database_info(self) -> dict:
        """
        Get database information and statistics.

        Returns:
            dict: Database information
        """
        try:
            db = next(get_db())

            # Get table statistics
            stats = {
                'users': db.query(User).count(),
                'projects': db.query(Project).count(),
                'documents': db.query(Document).count(),
                'document_chunks': db.query(DocumentChunk).count(),
                'document_summaries': db.query(DocumentSummary).count(),
                'api_call_logs': db.query(APICallLog).count()
            }

            # Get database size (SQLite only)
            if self.engine.url.drivername == 'sqlite':
                cursor = db.execute(text("SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size()"))
                size_result = cursor.fetchone()
                stats['database_size_bytes'] = size_result[0] if size_result else 0

            return stats

        except Exception as e:
            logger.error(f"Error getting database info: {e}")
            return {}
        finally:
            db.close()

def initialize_database():
    """Legacy function for backward compatibility."""
    initializer = DatabaseInitializer()
    return initializer.initialize_database()

def create_initial_data():
    """Legacy function for backward compatibility."""
    initializer = DatabaseInitializer()
    return initializer.create_initial_data()

def migrate_from_json_to_database():
    """Legacy function for backward compatibility."""
    initializer = DatabaseInitializer()
    return initializer.migrate_from_json_to_database()

def add_sample_data():
    """Legacy function for backward compatibility."""
    initializer = DatabaseInitializer()
    return initializer.add_sample_data()

if __name__ == '__main__':
    print("Initializing database with SQLAlchemy...")

    initializer = DatabaseInitializer()

    # Initialize database
    if initializer.initialize_database(drop_existing=True):
        print("✅ Database initialized successfully!")

        # Verify integrity
        if initializer.verify_database_integrity():
            print("✅ Database integrity verified!")

            # Get database info
            info = initializer.get_database_info()
            print(f"📊 Database statistics: {info}")

            # Create initial data
            if initializer.create_initial_data():
                print("✅ Initial data created successfully!")

            # Try JSON migration (if applicable)
            if initializer.migrate_from_json_to_database():
                print("✅ JSON migration completed!")

            # Add sample data (uncomment to enable)
            # if initializer.add_sample_data():
            #     print("✅ Sample data added successfully!")
            # else:
            #     print("❌ Failed to add sample data")
        else:
            print("❌ Database integrity check failed")
    else:
        print("❌ Database initialization failed")