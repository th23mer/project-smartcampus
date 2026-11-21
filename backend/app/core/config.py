"""Réglages de l'application (SA-7).

Sources, de la plus prioritaire à la moins prioritaire :
1. arguments passés au constructeur (tests) ;
2. variables d'environnement (`APP_ENV`, `DATABASE_URL`…) ;
3. fichiers `.env` (jamais commités) : celui de la racine du dépôt (partagé avec Docker
   Compose, SA-16), puis `backend/.env` qui le surcharge ;
4. fichier YAML non secret `backend/config/app.yaml` ;
5. valeurs par défaut ci-dessous.

Les secrets (identifiants de base, clés d'API) ne viennent que des sources 2 et 3.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, computed_field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from app.config.loader import load_yaml_config

BACKEND_DIR: Path = Path(__file__).resolve().parents[2]
REPO_DIR: Path = BACKEND_DIR.parent

AppEnv = Literal["dev", "test", "staging", "prod"]

#: Environnements où l'authentification simulée par en-têtes `X-Dev-*` est permise.
DEV_AUTH_ENVS: frozenset[str] = frozenset({"dev", "test"})


class _YamlSource(PydanticBaseSettingsSource):
    """Source pydantic-settings qui lit `backend/config/app.yaml`."""

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        # Non utilisé : __call__ renvoie directement le dictionnaire complet.
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        data = load_yaml_config("app")
        return {key: value for key, value in data.items() if key in self.settings_cls.model_fields}


class Settings(BaseSettings):
    """Réglages typés du backend."""

    model_config = SettingsConfigDict(
        # Le dernier fichier l'emporte : backend/.env surcharge le .env racine (SA-16).
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application ---
    app_env: AppEnv = "dev"
    app_name: str = "SmartCampus AI"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    log_level: str = "INFO"
    log_json: bool = True

    # --- Base de données (secrets : uniquement par l'environnement) ---
    #: URL async de l'application, ex. postgresql+asyncpg://user:***@hote:5432/base
    database_url: str | None = None
    #: URL sync des migrations Alembic, ex. postgresql+psycopg://owner:***@hote:5432/base
    migration_database_url: str | None = None
    #: URL async lecture seule de l'outil RAG (rôle smartcampus_rag_reader, SA-16) ; E4.
    rag_reader_database_url: str | None = None
    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    db_echo: bool = False
    db_ready_timeout_s: float = Field(default=2.0, gt=0)

    @field_validator("database_url")
    @classmethod
    def _check_async_driver(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL doit utiliser le pilote async : postgresql+asyncpg://")
        return value

    @field_validator("migration_database_url")
    @classmethod
    def _check_sync_driver(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("postgresql+psycopg://"):
            raise ValueError(
                "MIGRATION_DATABASE_URL doit utiliser le pilote sync : postgresql+psycopg://"
            )
        return value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def dev_auth_enabled(self) -> bool:
        """Vrai si l'authentification simulée (en-têtes X-Dev-*) est autorisée."""
        return self.app_env in DEV_AUTH_ENVS

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _YamlSource(settings_cls),
            file_secret_settings,
        )


@lru_cache
def get_settings() -> Settings:
    """Réglages partagés (mis en cache). Les tests passent leurs propres `Settings`."""
    return Settings()
