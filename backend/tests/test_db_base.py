"""Convention de nommage des contraintes (SA-12 §0) appliquée par `Base`."""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import CreateIndex, CreateTable

from app.core.config import Settings
from app.core.db import Base


class _Parent(Base):
    __tablename__ = "zz_parent"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)


class _Child(Base):
    __tablename__ = "zz_child"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    parent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("zz_parent.id"))
    code: Mapped[str] = mapped_column(String(32))
    __table_args__ = (
        UniqueConstraint("parent_id", "code"),
        CheckConstraint("code <> ''", name="code_not_empty"),
        ExcludeConstraint(("code", "="), name="one_published", using="gist"),
        Index(None, "code"),
    )


def test_naming_convention():
    ddl = str(CreateTable(_Child.__table__).compile(dialect=postgresql.dialect()))
    assert "CONSTRAINT pk_zz_child PRIMARY KEY" in ddl
    assert "CONSTRAINT fk_zz_child_parent_id FOREIGN KEY" in ddl
    assert "CONSTRAINT uq_zz_child_parent_id_code UNIQUE" in ddl
    assert "CONSTRAINT ck_zz_child_code_not_empty CHECK" in ddl
    assert "CONSTRAINT ex_zz_child_one_published EXCLUDE" in ddl
    idx = next(iter(_Child.__table__.indexes))
    assert "ix_zz_child_code" in str(CreateIndex(idx).compile(dialect=postgresql.dialect()))
    # Ne pas polluer les métadonnées réelles (Alembic).
    Base.metadata.remove(_Child.__table__)
    Base.metadata.remove(_Parent.__table__)


def test_settings_reject_sync_driver_for_app():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="postgresql://u:p@h/db")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            migration_database_url="postgresql+asyncpg://u:p@h/db",
        )


def test_yaml_config_loaded():
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert "http://localhost:3000" in s.cors_origins
    assert s.api_prefix == "/api/v1"
