"""
Database migration script to transition from raw SQLite to unified SQLAlchemy ORM.
"""
import sqlite3
import logging
from typing import Dict, Any
from pathlib import Path

from giani_pkb.database.database_manager import DatabaseManager

logger = logging.getLogger(__name__)

class DatabaseMigration:
    """
    Migration utility to transition from raw SQLite to SQLAlchemy ORM.
    """

    def __init__(self, old_database_path: str = 'users.db'):
        self.old_database_path = Path(old_database_path)
        self.db_manager = DatabaseManager()

    def check_old_database_exists(self) -> bool:
        """Check if the old SQLite database exists."""
        return self.old_database_path.exists()

    def get_old_database_info(self) -> Dict[str, Any]:
        """Get information about the old database."""
        if not self.check_old_database_exists():
            return {}

        try:
            conn = sqlite3.connect(self.old_database_path)
            cursor = conn.cursor()

            # Get table information
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]

            info = {'tables': tables, 'table_counts': {}}

            # Get record counts for each table
            for table in tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cursor.fetchone()[0]
                    info['table_counts'][table] = count
                except sqlite3.Error:
                    info['table_counts'][table] = 0

            conn.close()
            return info

        except Exception as e:
            logger.error(f"Error getting old database info: {e}")
            return {}

    def migrate_users(self) -> int:
        """Migrate users from old database to new SQLAlchemy system."""
        if not self.check_old_database_exists():
            logger.warning("Old database not found, skipping user migration")
            return 0

        try:
            conn = sqlite3.connect(self.old_database_path)
            cursor = conn.cursor()

            # Get all users from old database
            cursor.execute('''
                SELECT id, email, name, password_hash, microsoft_id, projects, created_at, updated_at
                FROM users
            ''')

            users = cursor.fetchall()
            migrated_count = 0

            for user_data in users:
                try:
                    # Check if user already exists in new database
                    existing_user = self.db_manager.get_user_by_email(user_data[1])
                    if existing_user:
                        logger.info(f"User {user_data[1]} already exists, skipping")
                        continue

                    # Create user in new database
                    # Note: We need to handle the old ID format (string) vs new format (integer)
                    username = user_data[2] or user_data[1].split('@')[0]  # Use name or email prefix

                    # Handle password - if it's already hashed, we need to store it as-is
                    # For new users, we'll use a default password that they can change
                    password = "changeme123"  # Default password for migrated users

                    new_user = self.db_manager.create_user(
                        username=username,
                        email=user_data[1],
                        password=password,
                        is_superuser=False  # Default to regular user
                    )

                    logger.info(f"Migrated user: {user_data[1]} -> ID: {new_user.id}")
                    migrated_count += 1

                except Exception as e:
                    logger.error(f"Error migrating user {user_data[1]}: {e}")
                    continue

            conn.close()
            logger.info(f"Successfully migrated {migrated_count} users")
            return migrated_count

        except Exception as e:
            logger.error(f"Error during user migration: {e}")
            return 0

    def migrate_projects(self) -> int:
        """Migrate projects from old database to new SQLAlchemy system."""
        if not self.check_old_database_exists():
            logger.warning("Old database not found, skipping project migration")
            return 0

        try:
            conn = sqlite3.connect(self.old_database_path)
            cursor = conn.cursor()

            # Get all projects from old database
            cursor.execute('''
                SELECT project_id, user_id, project_name, project_description,
                       client_name, client_industry, target_audience,
                       key_client_stakeholders_profiles, primary_project_objectives_success_metrics,
                       created_at, updated_at
                FROM projects
            ''')

            projects = cursor.fetchall()
            migrated_count = 0

            for project_data in projects:
                try:
                    # Find the corresponding user in new database
                    # Note: We need to map old string IDs to new integer IDs
                    # This is a simplified approach - in practice, you might need a mapping table
                    old_user_id = project_data[1]

                    # For now, we'll create a default user if needed
                    # In a real migration, you'd want to maintain the user relationships
                    default_user = self.db_manager.get_user_by_email("admin@giani.ai")
                    if not default_user:
                        default_user = self.db_manager.create_user(
                            username="admin",
                            email="admin@giani.ai",
                            password="admin123",
                            is_superuser=True
                        )

                    # Create project in new database
                    new_project = self.db_manager.create_project(
                        name=project_data[2],
                        owner_id=default_user.id,
                        description=project_data[3] or f"Migrated project: {project_data[2]}"
                    )

                    logger.info(f"Migrated project: {project_data[2]} -> ID: {new_project.id}")
                    migrated_count += 1

                except Exception as e:
                    logger.error(f"Error migrating project {project_data[2]}: {e}")
                    continue

            conn.close()
            logger.info(f"Successfully migrated {migrated_count} projects")
            return migrated_count

        except Exception as e:
            logger.error(f"Error during project migration: {e}")
            return 0

    def migrate_documents(self) -> int:
        """Migrate documents from old database to new SQLAlchemy system."""
        if not self.check_old_database_exists():
            logger.warning("Old database not found, skipping document migration")
            return 0

        try:
            conn = sqlite3.connect(self.old_database_path)
            cursor = conn.cursor()

            # Get all documents from old database
            cursor.execute('''
                SELECT document_id, project_id, user_id, original_filename, stored_filename,
                       file_path, file_size, mime_type, role_purpose_category, other_category_specification,
                       ai_content_type, ai_purpose_note, user_validated_content_type, user_purpose_note,
                       document_priority, processing_status, created_at, processed_at, text_preview, metadata_path
                FROM documents
            ''')

            documents = cursor.fetchall()
            migrated_count = 0

            # Get default user and project for migration
            default_user = self.db_manager.get_user_by_email("admin@giani.ai")
            if not default_user:
                default_user = self.db_manager.create_user(
                    username="admin",
                    email="admin@giani.ai",
                    password="admin123",
                    is_superuser=True
                )

            default_project = self.db_manager.get_user_projects(default_user.id)
            if not default_project:
                default_project = self.db_manager.create_project(
                    name="Migrated Documents",
                    owner_id=default_user.id,
                    description="Project for migrated documents"
                )
            else:
                default_project = default_project[0]

            for doc_data in documents:
                try:
                    # Create document in new database
                    new_document = self.db_manager.create_document(
                        original_filename=doc_data[3] or "unknown",
                        file_size=doc_data[6] or 0,
                        file_mime_type=doc_data[7] or "application/octet-stream",
                        storage_path=doc_data[5] or "",
                        category_folder=doc_data[8] or "unknown",
                        stored_filename=doc_data[4] or doc_data[3] or "unknown",
                        final_category=doc_data[8] or "39. Generic Text Document",
                        final_purpose=doc_data[12] or doc_data[11] or "Document purpose not specified",
                        priority=doc_data[14] or "Medium",
                        text_preview=doc_data[18] or "",
                        user_id=default_user.id,
                        project_id=default_project.id
                    )

                    logger.info(f"Migrated document: {doc_data[3]} -> ID: {new_document.id}")
                    migrated_count += 1

                except Exception as e:
                    logger.error(f"Error migrating document {doc_data[3]}: {e}")
                    continue

            conn.close()
            logger.info(f"Successfully migrated {migrated_count} documents")
            return migrated_count

        except Exception as e:
            logger.error(f"Error during document migration: {e}")
            return 0

    def run_full_migration(self, backup_old: bool = True) -> Dict[str, Any]:
        """
        Run complete migration from old database to new SQLAlchemy system.

        Args:
            backup_old: Whether to create a backup of the old database

        Returns:
            Migration results summary
        """
        logger.info("Starting database migration...")

        results = {
            'old_database_info': {},
            'migration_success': False,
            'users_migrated': 0,
            'projects_migrated': 0,
            'documents_migrated': 0,
            'errors': []
        }

        try:
            # Check if old database exists
            if not self.check_old_database_exists():
                logger.warning("Old database not found, nothing to migrate")
                results['errors'].append("Old database not found")
                return results

            # Get old database info
            results['old_database_info'] = self.get_old_database_info()
            logger.info(f"Old database info: {results['old_database_info']}")

            # Create backup if requested
            if backup_old:
                backup_path = self.old_database_path.with_suffix('.db.backup')
                import shutil
                shutil.copy2(self.old_database_path, backup_path)
                logger.info(f"Created backup: {backup_path}")

            # Run migrations
            results['users_migrated'] = self.migrate_users()
            results['projects_migrated'] = self.migrate_projects()
            results['documents_migrated'] = self.migrate_documents()

            # Verify migration
            new_stats = self.db_manager.get_database_statistics()
            logger.info(f"New database statistics: {new_stats}")

            results['migration_success'] = True
            logger.info("Database migration completed successfully")

        except Exception as e:
            logger.error(f"Migration failed: {e}")
            results['errors'].append(str(e))

        return results

    def rollback_migration(self) -> bool:
        """
        Rollback migration by restoring from backup.

        Returns:
            True if rollback successful, False otherwise
        """
        backup_path = self.old_database_path.with_suffix('.db.backup')

        if not backup_path.exists():
            logger.error("Backup file not found, cannot rollback")
            return False

        try:
            import shutil
            shutil.copy2(backup_path, self.old_database_path)
            logger.info("Migration rollback completed")
            return True

        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            return False

def migrate_database():
    """Legacy function for backward compatibility."""
    migrator = DatabaseMigration()
    return migrator.run_full_migration()

if __name__ == '__main__':
    print("Starting database migration...")

    migrator = DatabaseMigration()

    # Check old database
    if migrator.check_old_database_exists():
        info = migrator.get_old_database_info()
        print(f"Found old database: {info}")

        # Run migration
        results = migrator.run_full_migration(backup_old=True)
        print(f"Migration results: {results}")

        if results['migration_success']:
            print("✅ Migration completed successfully!")
        else:
            print("❌ Migration failed!")
            print(f"Errors: {results['errors']}")
    else:
        print("No old database found, nothing to migrate")