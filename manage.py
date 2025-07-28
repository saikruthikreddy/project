#!/usr/bin/env python3
"""
Database management script for Giani AI Project Knowledge Base.
Enhanced with proper migration workflow.
"""

import os
import sys
import click
from pathlib import Path

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from giani_pkb.database.database_initialize import DatabaseInitializer
from giani_pkb.database.database_migration import DatabaseMigration
from giani_pkb.database.database_manager import DatabaseManager

@click.group()
def cli():
    """Giani AI Database Management Tool"""
    pass

@cli.command()
@click.option('--message', '-m', required=True, help='Migration message')
def create_migration(message):
    """Create a new migration."""
    click.echo(f"📝 Creating migration: {message}")
    try:
        db_manager = DatabaseManager()
        if db_manager.create_migration(message):
            click.echo("✅ Migration created successfully!")
            click.echo("📝 Review the migration file before applying")
            click.echo("📝 Apply it with: python manage.py apply")
        else:
            click.echo("❌ Failed to create migration")
            sys.exit(1)
    except ImportError:
        click.echo("❌ Alembic not installed. Please install it with: pip install alembic")
        sys.exit(1)

@cli.command()
@click.option('--revision', default='head', help='Revision to upgrade to (default: head)')
@click.option('--sql', is_flag=True, help='Generate SQL instead of applying')
def apply(revision, sql):
    """Apply database migrations."""
    if sql:
        click.echo(f"🔄 Generating SQL for migrations to: {revision}")
        try:
            import subprocess
            result = subprocess.run([
                'alembic', 'upgrade', revision, '--sql'
            ], capture_output=True, text=True)

            if result.returncode == 0:
                click.echo("Generated SQL:")
                click.echo(result.stdout)
            else:
                click.echo("❌ Failed to generate SQL")
                click.echo(result.stderr)
        except ImportError:
            click.echo("❌ Alembic not installed")
            sys.exit(1)
    else:
        click.echo(f"🔄 Applying migrations to: {revision}")
        try:
            db_manager = DatabaseManager()
            if db_manager.run_migrations(revision):
                click.echo("✅ Migrations applied successfully!")
            else:
                click.echo("❌ Failed to apply migrations")
                sys.exit(1)
        except ImportError:
            click.echo("❌ Alembic not installed")
            sys.exit(1)

@cli.command()
def status():
    """Show migration status."""
    click.echo("📊 Migration Status:")
    try:
        db_manager = DatabaseManager()
        status_info = db_manager.get_migration_status()

        if status_info['status'] == 'success':
            click.echo(f"Current revision: {status_info['current_revision']}")
            click.echo("\nMigration history:")
            click.echo(status_info['history'])
        else:
            click.echo(f"❌ Error: {status_info.get('error', 'Unknown error')}")
    except ImportError:
        click.echo("❌ Alembic not installed")
        sys.exit(1)

@cli.command()
@click.option('--steps', default=1, help='Number of steps to downgrade')
@click.confirmation_option(prompt='Are you sure you want to downgrade?')
def downgrade(steps):
    """Downgrade database migrations."""
    click.echo(f"⬇️ Downgrading {steps} step(s)...")
    try:
        import subprocess
        target = f"-{steps}"
        result = subprocess.run([
            'alembic', 'downgrade', target
        ], capture_output=True, text=True)

        if result.returncode == 0:
            click.echo("✅ Downgrade completed successfully!")
        else:
            click.echo("❌ Downgrade failed")
            click.echo(result.stderr)
            sys.exit(1)
    except ImportError:
        click.echo("❌ Alembic not installed")
        sys.exit(1)

@cli.command()
def init_alembic():
    """Initialize Alembic migrations if not already done."""
    click.echo("🔧 Initializing Alembic...")

    if Path("migrations").exists():
        click.echo("⚠️ Migrations directory already exists")
        return

    try:
        import subprocess
        result = subprocess.run(['alembic', 'init', 'migrations'],
                              capture_output=True, text=True)

        if result.returncode == 0:
            click.echo("✅ Alembic initialized successfully!")
            click.echo("📝 Creating initial migration...")

            # Create initial migration
            result = subprocess.run([
                'alembic', 'revision', '--autogenerate', '-m', 'Initial migration'
            ], capture_output=True, text=True)

            if result.returncode == 0:
                click.echo("✅ Initial migration created!")
            else:
                click.echo("⚠️ Could not create initial migration")
        else:
            click.echo("❌ Failed to initialize Alembic")
            click.echo(result.stderr)
    except ImportError:
        click.echo("❌ Alembic not installed. Install with: pip install alembic")
        sys.exit(1)

# Keep your existing commands...
@cli.command()
@click.option('--drop-existing', is_flag=True, help='Drop existing tables before initialization')
def init_db(drop_existing):
    """Initialize database (legacy method - use migrations instead)."""
    click.echo("⚠️ WARNING: This will recreate all tables!")
    click.echo("⚠️ Consider using migrations instead: python manage.py create-migration")

    if not click.confirm('Do you want to continue?'):
        return

    click.echo("🔧 Initializing database...")
    initializer = DatabaseInitializer()

    if initializer.initialize_database(drop_existing=drop_existing):
        click.echo("✅ Database initialized successfully!")

        if initializer.create_initial_data():
            click.echo("✅ Initial data created!")

        # Mark current state as migrated
        try:
            import subprocess
            subprocess.run(['alembic', 'stamp', 'head'], check=True)
            click.echo("✅ Marked current schema as up-to-date")
        except:
            click.echo("⚠️ Could not mark schema as migrated")
    else:
        click.echo("❌ Database initialization failed")
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

if __name__ == '__main__':
    cli()