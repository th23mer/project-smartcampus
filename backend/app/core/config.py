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

from pydantic import Field, SecretStr, computed_field, field_validator
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

    # --- Authentification (SA-28, E3) : SA-5 §1.2, décision D3 ---
    #: Secret de signature HS256 des jetons d'accès (≥ 32 caractères, uniquement par l'env).
    #: Absent : connexion et inscription répondent 503, tout jeton Bearer est refusé.
    jwt_secret: SecretStr | None = None
    jwt_issuer: str = "smartcampus-ai"
    #: Jeton d'accès : 15 min (SA-5 §1.2).
    access_token_ttl_s: int = Field(default=900, gt=0)
    #: Jeton de renouvellement (cookie `sc_refresh`) : 7 jours, rotation à chaque usage.
    refresh_token_ttl_days: int = Field(default=7, gt=0)
    #: Cookies `Secure` ; None = automatique (désactivé en dev/test, actif ailleurs).
    cookie_secure: bool | None = None
    #: Anti-force brute de la connexion : 5 échecs / 15 min / IP + e-mail (SA-5).
    login_max_failures: int = Field(default=5, gt=0)
    login_window_s: int = Field(default=900, gt=0)
    #: Version de la politique de confidentialité inscrite dans le journal des consentements.
    consent_policy_version: str = "2026-11"

    # --- Sessions visiteur et mémoire (SA-25, SA-26) : décision D-D ---
    visitor_idle_ttl_h: int = Field(default=24, gt=0)
    visitor_max_lifetime_days: int = Field(default=7, gt=0)
    #: Quota : 30 messages par fenêtre de 24 h.
    visitor_message_quota: int = Field(default=30, gt=0)
    visitor_quota_window_h: int = Field(default=24, gt=0)
    #: Purge des sessions expirées (et de leurs conversations) 30 jours après l'expiration.
    visitor_purge_after_days: int = Field(default=30, gt=0)
    #: Mémoire de travail transmise à l'agent : N derniers messages de la conversation.
    memory_context_messages: int = Field(default=20, gt=0)
    message_max_chars: int = Field(default=2000, gt=0)
    #: Durée de validité d'une offre de rattachement (SA-29).
    attach_offer_ttl_min: int = Field(default=30, gt=0)

    @field_validator("jwt_secret", mode="before")
    @classmethod
    def _empty_jwt_secret(cls, value: object) -> object:
        """Variable vide (compose sans JWT_SECRET) = absente."""
        return None if value == "" else value

    @field_validator("jwt_secret")
    @classmethod
    def _check_jwt_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET doit contenir au moins 32 caractères.")
        return value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cookies_secure(self) -> bool:
        """Attribut `Secure` des cookies (HTTPS) : actif hors dev/test sauf réglage explicite."""
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.app_env not in DEV_AUTH_ENVS

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
