"""Accès à PostgreSQL : moteur async, sessions, base déclarative (SA-7).

- Moteur **async** (SQLAlchemy 2 + asyncpg) créé paresseusement à partir de `DATABASE_URL`.
- `get_session` : dépendance FastAPI, une session par requête (commit explicite dans les
  services, rollback automatique en cas d'exception).
- `Base` : base déclarative commune à tous les modèles (SA-17), avec la convention de
  nommage des contraintes de SA-12 §0.

Convention de nommage (SA-12 §0) et usage attendu dans les modèles :

| Type | Gabarit | Nom donné dans le modèle |
|---|---|---|
| clé primaire | `pk_<table>` | aucun |
| clé étrangère | `fk_<table>_<colonne>` | aucun, ou nom complet |
| unicité | `uq_<table>_<colonnes>` | aucun, ou nom complet |
| index | `ix_<table>_<colonnes>` | aucun, ou nom complet |
| CHECK | `ck_<table>_<règle>` | la règle seule : `name="four_eyes"` |
| exclusion | `ex_<table>_<règle>` | la règle seule : `name="one_published"` |

Pour CHECK et EXCLUDE, le gabarit utilise `%(constraint_name)s` : donner seulement la
règle (sinon le préfixe serait doublé). Pour un nom déjà complet, utiliser
`sqlalchemy.sql.elements.conv("ck_...")`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import MetaData, text
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings, get_settings
from app.core.errors import AppError, ErrorCode

#: Convention de nommage des contraintes (SA-12 §0).
NAMING_CONVENTION: dict = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    ExcludeConstraint: "ex_%(table_name)s_%(constraint_name)s",
}


class Base(DeclarativeBase):
    """Base déclarative commune. Les modèles (SA-17) héritent de cette classe."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def create_engine_from_settings(settings: Settings) -> AsyncEngine:
    """Crée un moteur async (aucune connexion n'est ouverte à la création)."""
    if not settings.database_url:
        raise AppError(
            ErrorCode.SERVICE_UNAVAILABLE,
            message="Base de données non configurée.",
            details={"missing": "DATABASE_URL"},
        )
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        echo=settings.db_echo,
    )


@lru_cache
def get_engine() -> AsyncEngine:
    """Moteur partagé du processus, créé au premier usage."""
    return create_engine_from_settings(get_settings())


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Fabrique de sessions partagée (expire_on_commit=False pour les réponses API)."""
    return async_sessionmaker(get_engine(), expire_on_commit=False, autoflush=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dépendance FastAPI : une `AsyncSession` par requête.

    Les services valident explicitement (`await session.commit()`) ; en cas d'exception
    la transaction est annulée.
    """
    async with get_sessionmaker()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def ping_database(engine: AsyncEngine) -> None:
    """Exécute `SELECT 1` (utilisé par /health/ready)."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def dispose_engine() -> None:
    """Ferme le pool à l'arrêt de l'application (si le moteur a été créé)."""
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
        get_engine.cache_clear()
        get_sessionmaker.cache_clear()
