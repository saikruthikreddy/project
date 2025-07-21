#!/usr/bin/env python3
"""
Database management script for Giani AI Project Knowledge Base.
Provides commands for database initialization, migrations, and maintenance.
"""
import os
import sys
import click
from pathlib import Path

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from giani_pkb.database.database_initialize import DatabaseInitializer
from giani_pkb.database.database_migration import DatabaseMigration


@click.group()
def cli():
    """Giani AI Database Management Tool"""
    pass


@cli.command()
@click.option('--drop-existing', is_flag=True, help='Drop existing tables before initialization')
@click.option('--create-sample-data', is_flag=True, help='Create sample data after initialization')
def init(drop_existing, create_sample_data):
    """Initialize the database with all required tables."""
    click.echo("🔧 Initializing database...")

    initializer = DatabaseInitializer()

    if initializer.initialize_database(drop_existing=drop_existing):
        click.echo("✅ Database initialized successfully!")

        if initializer.verify_database_integrity():
            click.echo("✅ Database integrity verified!")

            if initializer.create_initial_data():
                click.echo("✅ Initial data created!")

            if create_sample_data:
                if initializer.add_sample_data():
                    click.echo("✅ Sample data added!")
                else:
                    click.echo("❌ Failed to add sample data")
        else:
            click.echo("❌ Database integrity check failed")
    else:
        click.echo("❌ Database initialization failed")
        sys.exit(1)


@cli.command()
def migrate():
    """Migrate data from old database format to new SQLAlchemy format."""
    click.echo("🔄 Starting database migration...")

    migrator = DatabaseMigration()

    if migrator.check_old_database_exists():
        info = migrator.get_old_database_info()
        click.echo(f"📊 Found old database: {info}")

        results = migrator.run_full_migration(backup_old=True)

        if results['migration_success']:
            click.echo("✅ Migration completed successfully!")
            click.echo(f"📈 Migrated: {results['users_migrated']} users, "
                      f"{results['projects_migrated']} projects, "
                      f"{results['documents_migrated']} documents")
        else:
            click.echo("❌ Migration failed!")
            for error in results['errors']:
                click.echo(f"   Error: {error}")
            sys.exit(1)
    else:
        click.echo("ℹ️  No old database found, nothing to migrate")


@cli.command()
def rollback():
    """Rollback the last migration."""
    click.echo("🔄 Rolling back migration...")

    migrator = DatabaseMigration()

    if migrator.rollback_migration():
        click.echo("✅ Migration rollback completed!")
    else:
        click.echo("❌ Migration rollback failed!")
        sys.exit(1)


@cli.command()
def info():
    """Show database information and statistics."""
    click.echo("📊 Database Information:")

    initializer = DatabaseInitializer()
    info = initializer.get_database_info()

    for key, value in info.items():
        click.echo(f"   {key}: {value}")


@cli.command()
def verify():
    """Verify database integrity."""
    click.echo("🔍 Verifying database integrity...")

    initializer = DatabaseInitializer()

    if initializer.verify_database_integrity():
        click.echo("✅ Database integrity verified!")
    else:
        click.echo("❌ Database integrity check failed!")
        sys.exit(1)


@cli.command()
@click.option('--overwrite', is_flag=True, help='Overwrite existing sample data')
def sample_data(overwrite):
    """Add sample data for testing and development."""
    click.echo("📝 Adding sample data...")

    initializer = DatabaseInitializer()

    if initializer.add_sample_data(overwrite=overwrite):
        click.echo("✅ Sample data added successfully!")
        click.echo("🔑 Test credentials: email=test@example.com, password=password123")
    else:
        click.echo("❌ Failed to add sample data")
        sys.exit(1)


@cli.command()
def alembic_init():
    """Initialize Alembic for database migrations."""
    click.echo("🔧 Initializing Alembic...")

    try:
        import subprocess

        # Check if alembic is installed
        result = subprocess.run(['alembic', '--version'], capture_output=True, text=True)
        if result.returncode != 0:
            click.echo("❌ Alembic not found. Please install it with: pip install alembic")
            sys.exit(1)

        # Initialize alembic
        result = subprocess.run(['alembic', 'init', 'migrations'], capture_output=True, text=True)
        if result.returncode != 0:
            click.echo("❌ Failed to initialize Alembic")
            click.echo(result.stderr)
            sys.exit(1)

        click.echo("✅ Alembic initialized successfully!")
        click.echo("📝 You can now create migrations with: alembic revision --autogenerate -m 'description'")
        click.echo("📝 Apply migrations with: alembic upgrade head")

    except ImportError:
        click.echo("❌ Alembic not installed. Please install it with: pip install alembic")
        sys.exit(1)


@cli.command()
@click.argument('message')
def create_migration(message):
    """Create a new migration."""
    click.echo(f"📝 Creating migration: {message}")

    try:
        import subprocess

        result = subprocess.run([
            'alembic', 'revision', '--autogenerate', '-m', message
        ], capture_output=True, text=True)

        if result.returncode == 0:
            click.echo("✅ Migration created successfully!")
            click.echo("📝 Apply it with: python manage.py apply-migrations")
        else:
            click.echo("❌ Failed to create migration")
            click.echo(result.stderr)
            sys.exit(1)

    except ImportError:
        click.echo("❌ Alembic not installed. Please install it with: pip install alembic")
        sys.exit(1)


@cli.command()
@click.option('--revision', default='head', help='Revision to upgrade to (default: head)')
def apply_migrations(revision):
    """Apply database migrations."""
    click.echo(f"🔄 Applying migrations to revision: {revision}")

    try:
        import subprocess

        result = subprocess.run([
            'alembic', 'upgrade', revision
        ], capture_output=True, text=True)

        if result.returncode == 0:
            click.echo("✅ Migrations applied successfully!")
        else:
            click.echo("❌ Failed to apply migrations")
            click.echo(result.stderr)
            sys.exit(1)

    except ImportError:
        click.echo("❌ Alembic not installed. Please install it with: pip install alembic")
        sys.exit(1)


@cli.command()
def migration_status():
    """Show migration status."""
    click.echo("📊 Migration Status:")

    try:
        import subprocess

        result = subprocess.run(['alembic', 'current'], capture_output=True, text=True)
        if result.returncode == 0:
            click.echo(result.stdout)
        else:
            click.echo("❌ Failed to get migration status")
            click.echo(result.stderr)
            sys.exit(1)

    except ImportError:
        click.echo("❌ Alembic not installed. Please install it with: pip install alembic")
        sys.exit(1)


@cli.command()
def history():
    """Show migration history."""
    click.echo("📜 Migration History:")

    try:
        import subprocess

        result = subprocess.run(['alembic', 'history'], capture_output=True, text=True)
        if result.returncode == 0:
            click.echo(result.stdout)
        else:
            click.echo("❌ Failed to get migration history")
            click.echo(result.stderr)
            sys.exit(1)

    except ImportError:
        click.echo("❌ Alembic not installed. Please install it with: pip install alembic")
        sys.exit(1)


if __name__ == '__main__':
    cli()