from logging.config import fileConfig
import os
import sys
from sqlalchemy import engine_from_config, pool, text
from alembic import context

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import your models and database configuration
from giani_pkb.models.database_models import Base
from giani_pkb.utils.config import config as app_config

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here for 'autogenerate' support
target_metadata = Base.metadata


def get_url():
    """Get database URL from environment or config."""
    # Try environment variable first (for different environments)
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    # Fall back to app config
    try:
        return app_config.DATABASE_URL
    except AttributeError:
        # Default for development
        return "sqlite:///giani_ai.db"


def include_object(object, name, type_, reflected, compare_to):
    """Include objects in migration based on certain criteria."""
    # Skip temporary tables or views if any
    if type_ == "table" and name.startswith("temp_"):
        return False
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    configuration = config.get_section(config.config_ini_section)

    # Override the URL in the config
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=True,
            compare_server_default=True,
            render_as_batch=True,  # Important for SQLite
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
