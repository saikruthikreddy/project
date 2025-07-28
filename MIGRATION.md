# Database Migration Guide

A focused documentation for setting up and managing database migrations in the Giani AI Project Knowledge Base.

## 🚀 Quick Setup

### 1. Prerequisites

- Python 3.8+
- PostgreSQL/SQLite database
- Alembic installed (`pip install alembic`)


### 2. Initial Migration Setup (One-time)

```bash
# Initialize Alembic (if not already done)
python manage.py init-alembic

# Or manually:
alembic init migrations
```

This creates:

- `migrations/` directory with version files
- `alembic.ini` configuration file
- `migrations/env.py` environment setup


## 📂 Important Migration Files

| File | Purpose | When to Modify |
| :-- | :-- | :-- |
| `alembic.ini` | Alembic configuration | Rarely (already configured) |
| `migrations/env.py` | Database connection setup | Rarely (already configured) |
| `migrations/versions/*.py` | Individual migration files | **Never edit after applying** |
| `manage.py` | Management commands | Never |
| `database_models.py` | Your data models | When adding/changing models |

## 🔄 Standard Workflow

### Step 1: Make Model Changes

Edit your models in `giani_pkb/models/database_models.py`:

```python
# Example: Adding a new field
class User(Base):
    # ... existing fields ...
    new_field = Column(String(100), nullable=False, default='default_value')
```


### Step 2: Create Migration

```bash
python manage.py create-migration -m "Add new_field to User model"
```


### Step 3: Review Generated Migration

**ALWAYS** check the generated file in `migrations/versions/` before applying:

- Verify the SQL commands look correct
- Check for data loss operations
- Ensure proper default values for NOT NULL columns


### Step 4: Apply Migration

```bash
# Apply to your local database
python manage.py apply

# Or specify revision
python manage.py apply --revision abc123
```


### Step 5: Commit to Git

```bash
git add migrations/versions/
git commit -m "Add migration: Add new_field to User model"
git push origin main
```


## 🛠️ Available Commands

### Management Commands

```bash
# Check migration status
python manage.py status

# Create new migration
python manage.py create-migration -m "Description"

# Apply migrations
python manage.py apply

# Apply to specific revision
python manage.py apply --revision abc123

# Rollback (use with caution)
python manage.py downgrade --steps 1

# Generate SQL without applying
python manage.py apply --sql
```


### Direct Alembic Commands

```bash
# Show current revision
alembic current

# Show migration history
alembic history

# Upgrade to latest
alembic upgrade head

# Downgrade one step
alembic downgrade -1
```


## ⚠️ Critical Points to Remember

### 🚨 Golden Rules

1. **NEVER edit applied migrations** - Create new ones instead
2. **ALWAYS review auto-generated migrations** before applying
3. **BACKUP production database** before major migrations
4. **Test migrations locally** before deploying

### 🔧 Common Pitfalls \& Solutions

#### Adding NOT NULL Columns

**❌ Wrong (will fail with existing data):**

```python
batch_op.add_column(sa.Column('required_field', sa.String(100), nullable=False))
```

**✅ Correct:**

```python
# Step 1: Add as nullable
batch_op.add_column(sa.Column('required_field', sa.String(100), nullable=True))

# Step 2: Update existing records
connection = op.get_bind()
connection.execute(sa.text("UPDATE users SET required_field = 'default' WHERE required_field IS NULL"))

# Step 3: Make NOT NULL
batch_op.alter_column('required_field', nullable=False)
```


#### Adding Unique Constraints

**✅ Safe approach:**

```python
# Ensure data is unique first, then add constraint
batch_op.create_unique_constraint('uq_users_email', ['email'])
```


### 🏭 Production Deployment

Migrations run automatically in production via `entrypoint.sh`:

```bash
python manage.py apply --revision head
```

No manual intervention needed during deployment.

## 🐛 Troubleshooting

### "Can't locate revision" Error

```bash
# Clear problematic revision from database
DELETE FROM alembic_version WHERE version_num = 'problematic_revision';

# Stamp to current state
alembic stamp head
```


### Migration Conflicts

1. Pull latest changes from main branch
2. If conflicts in migration files, delete your local migration
3. Create a new migration after pulling latest

### Rollback Emergency

```bash
# Check current revision
python manage.py status

# Rollback to previous
python manage.py downgrade --steps 1

# Or restore from backup
pg_restore your_backup.sql
```


## 📋 Team Workflow Checklist

### Before Creating Migration

- [ ] Pull latest changes from main
- [ ] Test model changes locally
- [ ] Consider impact on existing data


### After Creating Migration

- [ ] Review generated migration file
- [ ] Test migration locally
- [ ] Commit migration file to Git
- [ ] Push to main branch


### Before Production Deploy

- [ ] Migration tested on staging
- [ ] Database backup created
- [ ] Team notified of deployment


## 🚀 Quick Reference

```bash
# Daily workflow
git pull origin main
python manage.py create-migration -m "Your change description"
python manage.py apply
git add migrations/versions/
git commit -m "Add migration: Your change"
git push origin main

# Check status anytime
python manage.py status
```


## 🆘 Need Help?

1. **Check migration status**: `python manage.py status`
2. **Review recent migrations**: `alembic history`
3. **Check database state**: Connect to DB and verify tables
4. **Emergency**: Contact team lead for production issues

<div style="text-align: center">⁂</div>

[^1]: database_initialize.py

[^2]: database_migration.py

[^3]: database_models.py

[^4]: metadata_manager.py

[^5]: database_utils.py

[^6]: database.py

[^7]: env.py

[^8]: 69225136cbe8_initial_schema.py

[^9]: entrypoint.sh

[^10]: alembic.ini

[^11]: manage.py

[^12]: main.py

[^13]: README.md

[^14]: deploy.yml

[^15]: base.Dockerfile.txt

[^16]: Dockerfile.txt

[^17]: 2025_07_28_1735-c51127effb58_add_test_column_with_default_value.py