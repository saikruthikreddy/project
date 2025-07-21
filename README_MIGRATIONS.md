# Database Migration Guide

This guide explains how to set up and use the database migration system for the Giani AI Project Knowledge Base.

## Overview

The project uses **Alembic** for database migrations, which is the standard migration tool for SQLAlchemy. This provides:

- **Version Control**: Track database schema changes over time
- **Rollback Capability**: Revert to previous database states
- **Team Collaboration**: Share database changes across team members
- **Production Safety**: Safe database updates in production environments

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Initialize the Database

```bash
# Initialize database with tables
python manage.py init

# Initialize with sample data
python manage.py init --create-sample-data

# Drop existing tables and reinitialize
python manage.py init --drop-existing
```

### 3. Create Your First Migration

```bash
# Create a migration for current schema
python manage.py create-migration "Initial schema"

# Apply the migration
python manage.py apply-migrations
```

## Migration Commands

### Basic Commands

```bash
# Initialize database
python manage.py init [--drop-existing] [--create-sample-data]

# Create a new migration
python manage.py create-migration "Description of changes"

# Apply migrations
python manage.py apply-migrations [--revision <revision>]

# Check migration status
python manage.py migration-status

# View migration history
python manage.py history

# Show database info
python manage.py info

# Verify database integrity
python manage.py verify
```

### Legacy Migration (Old Database)

```bash
# Migrate from old database format
python manage.py migrate

# Rollback migration
python manage.py rollback
```

### Sample Data

```bash
# Add sample data for testing
python manage.py sample-data

# Overwrite existing sample data
python manage.py sample-data --overwrite
```

## Migration Workflow

### 1. Development Workflow

```bash
# 1. Make changes to your models in giani_pkb/models/database_models.py

# 2. Create a migration
python manage.py create-migration "Add new user fields"

# 3. Review the generated migration file in migrations/versions/

# 4. Apply the migration
python manage.py apply-migrations

# 5. Test your changes
python manage.py verify
```

### 2. Production Deployment

```bash
# 1. Check current migration status
python manage.py migration-status

# 2. Apply all pending migrations
python manage.py apply-migrations

# 3. Verify database integrity
python manage.py verify
```

## Migration Files

### Structure

```
migrations/
├── env.py              # Alembic environment configuration
├── script.py.mako      # Migration script template
├── versions/           # Migration files
│   ├── __init__.py
│   ├── 0001_initial_schema.py
│   ├── 0002_add_user_fields.py
│   └── ...
└── __init__.py
```

### Migration File Example

```python
"""Add user profile fields

Revision ID: 0002
Revises: 0001
Create Date: 2024-01-15 10:30:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Add new columns
    op.add_column('users', sa.Column('phone', sa.String(20), nullable=True))
    op.add_column('users', sa.Column('address', sa.Text(), nullable=True))

def downgrade() -> None:
    # Remove columns
    op.drop_column('users', 'address')
    op.drop_column('users', 'phone')
```

## Database Configuration

### Environment Variables

Set these environment variables for database configuration:

```bash
# SQLite (default)
DATABASE_URL=sqlite:///giani_ai.db

# PostgreSQL
DATABASE_URL=postgresql://user:password@localhost/giani_ai

# MySQL
DATABASE_URL=mysql://user:password@localhost/giani_ai
```

### Configuration File

You can also configure the database in `giani_pkb/utils/config.py`:

```python
class Config:
    DATABASE_URL = "sqlite:///giani_ai.db"
    # ... other config
```

## Troubleshooting

### Common Issues

#### 1. Migration Conflicts

If you have migration conflicts:

```bash
# Check current status
python manage.py migration-status

# View history
python manage.py history

# If needed, reset migrations
rm -rf migrations/versions/*
python manage.py create-migration "Fresh start"
```

#### 2. Database Lock Issues

For SQLite database locks:

```bash
# Check if database is in use
lsof giani_ai.db

# Restart your application
# Then run migrations
python manage.py apply-migrations
```

#### 3. Model Import Errors

If you get import errors:

```bash
# Make sure you're in the project root
cd /path/to/project

# Set PYTHONPATH
export PYTHONPATH=$PYTHONPATH:$(pwd)

# Run migration
python manage.py create-migration "Fix imports"
```

### Debugging

#### Enable Debug Logging

```bash
# Set environment variable
export ALEMBIC_LOG_LEVEL=DEBUG

# Run migration with verbose output
python manage.py apply-migrations
```

#### Check Migration SQL

```bash
# Generate SQL without executing
alembic upgrade head --sql

# Check specific revision
alembic upgrade 0002 --sql
```

## Best Practices

### 1. Migration Naming

Use descriptive names for migrations:

```bash
# Good
python manage.py create-migration "Add user profile fields"
python manage.py create-migration "Create document categories table"
python manage.py create-migration "Add indexes for performance"

# Bad
python manage.py create-migration "Update"
python manage.py create-migration "Fix"
```

### 2. Migration Size

Keep migrations small and focused:

- **Good**: One logical change per migration
- **Bad**: Multiple unrelated changes in one migration

### 3. Testing Migrations

Always test migrations:

```bash
# Test upgrade
python manage.py apply-migrations

# Test downgrade
alembic downgrade -1

# Test upgrade again
python manage.py apply-migrations
```

### 4. Backup Before Migration

```bash
# Create backup
cp giani_ai.db giani_ai.db.backup

# Run migration
python manage.py apply-migrations

# If issues, restore
cp giani_ai.db.backup giani_ai.db
```

## Advanced Features

### 1. Data Migrations

For data migrations, add custom logic:

```python
def upgrade() -> None:
    # Schema changes
    op.add_column('users', sa.Column('status', sa.String(20), nullable=True))

    # Data migration
    connection = op.get_bind()
    connection.execute(
        "UPDATE users SET status = 'active' WHERE status IS NULL"
    )

def downgrade() -> None:
    op.drop_column('users', 'status')
```

### 2. Conditional Migrations

```python
def upgrade() -> None:
    # Check if column exists
    inspector = inspect(op.get_bind())
    columns = [col['name'] for col in inspector.get_columns('users')]

    if 'new_column' not in columns:
        op.add_column('users', sa.Column('new_column', sa.String(50)))
```

### 3. Custom Migration Operations

```python
from alembic.operations import Operations

def upgrade() -> None:
    # Custom operation
    op.execute("CREATE INDEX idx_users_email ON users(email)")
```

## Integration with CI/CD

### GitHub Actions Example

```yaml
name: Database Migration
on: [push, pull_request]

jobs:
  migrate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.9'
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run migrations
        run: python manage.py apply-migrations
      - name: Verify database
        run: python manage.py verify
```

## Support

For migration issues:

1. Check the logs: `python manage.py migration-status`
2. Review migration history: `python manage.py history`
3. Verify database integrity: `python manage.py verify`
4. Check the Alembic documentation: https://alembic.sqlalchemy.org/

## Migration Checklist

Before deploying migrations to production:

- [ ] Test migrations on development database
- [ ] Verify rollback works correctly
- [ ] Check database integrity after migration
- [ ] Backup production database
- [ ] Test application functionality
- [ ] Monitor application logs during migration
- [ ] Have rollback plan ready