"""Integration tests for Alembic database migrations and schema state."""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.database.session import async_engine, get_db_session
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection


@pytest.fixture(autouse=True)
async def cleanup_database_engine() -> AsyncGenerator[None, None]:
    """Dispose engine connections between isolated test event loops."""
    yield
    await async_engine.dispose()


def test_alembic_config_and_script_directory() -> None:
    """Verify that alembic.ini is present and points to the valid migration scripts."""
    alembic_ini_path = Path("alembic.ini").resolve()
    assert alembic_ini_path.is_file(), f"alembic.ini not found at {alembic_ini_path}"

    config = Config(str(alembic_ini_path))
    script_dir = ScriptDirectory.from_config(config)

    heads = script_dir.get_heads()
    assert len(heads) == 1
    assert heads[0] == "b2f69a12c841"


@pytest.mark.integration
async def test_applied_migration_revision_in_database() -> None:
    """Verify the database tracks the expected Alembic migration revision."""
    async for session in get_db_session():
        result = await session.execute(text("SELECT version_num FROM alembic_version;"))
        current_rev = result.scalar()
        assert current_rev == "b2f69a12c841"


@pytest.mark.integration
async def test_migrated_tables_exist_in_database() -> None:
    """Verify all domain model tables are present in the migrated PostgreSQL 16 schema."""
    async with async_engine.connect() as conn:

        def verify_tables(sync_conn: Connection) -> None:
            insp = inspect(sync_conn)
            tables = set(insp.get_table_names())
            expected = {
                "repositories",
                "pull_requests",
                "review_runs",
                "evidence_items",
                "findings",
                "webhook_deliveries",
                "alembic_version",
            }
            assert expected.issubset(tables)

        await conn.run_sync(verify_tables)
