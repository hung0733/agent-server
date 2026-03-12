from logging.config import fileConfig
import os
from pathlib import Path

from sqlalchemy import engine_from_config, create_engine
from sqlalchemy import pool

from alembic import context

# Import all models here so that they are registered with Base.metadata
from db.models import Base
from global_var import GlobalVar

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Load database configuration from .env file
def get_db_url_from_env() -> str:
    """Read database configuration from .env file and construct the database URL."""
    env_path = Path(__file__).parent.parent / ".env"
    env_vars = {}
    
    if env_path.exists():
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    # Remove quotes and whitespace
                    env_vars[key.strip()] = value.strip().strip('"\'')
    
    user = env_vars.get("DB_USER", "postgres")
    password = env_vars.get("DB_PASSWORD", "")
    host = env_vars.get("DB_HOST", "localhost")
    port = env_vars.get("DB_PORT", "5432")
    database = env_vars.get("DB_NAME", "postgres")
    
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    from sqlalchemy import text
    
    # Use database URL from .env file
    sync_url = get_db_url_from_env()
    
    connectable = create_engine(sync_url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        # 確保 vector extension 已安裝
        try:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except Exception:
            pass  # Extension might already exist
        
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True  # Support SQLite compatibility if needed
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()