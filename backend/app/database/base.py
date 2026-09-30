"""SQLAlchemy 2.x Declarative Base and naming convention configuration."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Explicit naming conventions for PostgreSQL constraints to avoid unnamed
# constraints and ensure deterministic migration diffs with Alembic.
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """SQLAlchemy Declarative Base for all persistent domain models."""

    metadata = MetaData(naming_convention=convention)
