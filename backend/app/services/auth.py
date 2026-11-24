"""Comptes, connexion et jetons (SA-28) : code déterministe, aucun LLM.

- Inscription publique : toujours un compte **candidat** (rôle `candidate`) ; les comptes
  staff sont créés hors API (`scripts/create_staff.py`) ou par l'admin (SA-5, plus tard).
- Consentements `terms_accepted` et `data_processing` obligatoires, inscrits dans le journal
  append-only `consent` (SA-13).
- Connexion : Argon2id, message identique pour un e-mail inconnu ou un mauvais mot de passe,
  5 échecs / 15 min / IP + e-mail (429 RATE_LIMITED), compte `disabled` → 403.
- Jetons : accès JWT 15 min ; renouvellement opaque 7 jours, haché, avec **rotation** ; la
  réutilisation d'un jeton déjà remplacé révoque toute sa famille (vol probable du cookie).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.passwords import hash_password, needs_rehash, verify_password
from app.core.tokens import (
    create_access_token,
    hash_opaque_token,
    new_opaque_token,
)
from app.models import CandidateProfile, Consent, RefreshToken, Role, UserAccount, UserRole
from app.schemas.auth import RegisterRequest, User

CANDIDATE_ROLE = "candidate"


def now_utc() -> datetime:
    return datetime.now(UTC)


@dataclass
class Identity:
    """Compte relu en base au moment d'émettre un jeton (rôles à jour)."""

    account: UserAccount
    roles: list[str]
    institution_id: uuid.UUID | None
    candidate_id: uuid.UUID | None

    def to_user(self) -> User:
        return User(
            id=self.account.id,
            account_type=self.account.account_type,  # type: ignore[arg-type]
            email=self.account.email,
            full_name=self.account.full_name,
            account_status=self.account.account_status,  # type: ignore[arg-type]
            roles=sorted(self.roles),
            candidate_id=self.candidate_id,
            created_at=self.account.created_at,
        )


@dataclass
class IssuedTokens:
    access_token: str
    expires_in: int
    refresh_token: str


async def load_identity(session: AsyncSession, user_id: uuid.UUID) -> Identity | None:
    account = await session.get(UserAccount, user_id)
    if account is None:
        return None
    rows = (
        await session.execute(
            select(Role.code, Role.institution_id)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id, UserRole.revoked_at.is_(None))
        )
    ).all()
    institution_id = next((r.institution_id for r in rows if r.institution_id), None)
    candidate_id = await session.scalar(
        select(CandidateProfile.id).where(CandidateProfile.user_id == user_id)
    )
    return Identity(account, [r.code for r in rows], institution_id, candidate_id)


async def _candidate_role_id(session: AsyncSession) -> uuid.UUID:
    """Rôle `candidate` du référentiel (créé s'il manque : base sans seed)."""
    await session.execute(
        insert(Role)
        .values(code=CANDIDATE_ROLE, label="Candidat", is_staff=False)
        .on_conflict_do_nothing(index_elements=["code"])
    )
    return await session.scalar(select(Role.id).where(Role.code == CANDIDATE_ROLE))  # type: ignore[return-value]


async def register(
    session: AsyncSession,
    settings: Settings,
    payload: RegisterRequest,
    visitor_session_id: uuid.UUID | None,
) -> Identity:
    """Crée un compte candidat ; 422 CONSENT_REQUIRED, 409 EMAIL_ALREADY_USED."""
    missing = [name for name, given in payload.consents.model_dump().items() if given is not True]
    if missing:
        raise AppError(ErrorCode.CONSENT_REQUIRED, details={"missing": missing})
    exists = await session.scalar(select(UserAccount.id).where(UserAccount.email == payload.email))
    if exists is not None:
        raise AppError(ErrorCode.EMAIL_ALREADY_USED)

    account = UserAccount(
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        phone=payload.phone,
        account_type="candidate",
        # Vérification de l'e-mail (POST /auth/verify-email) : hors périmètre de ce lot.
        account_status="pending_verification",
    )
    session.add(account)
    await session.flush()
    session.add(UserRole(user_id=account.id, role_id=await _candidate_role_id(session)))
    for consent_type in ("terms_accepted", "data_processing"):
        session.add(
            Consent(
                user_id=account.id,
                visitor_session_id=visitor_session_id,
                consent_type=consent_type,
                granted=True,
                policy_version=settings.consent_policy_version,
                channel="web_form",
            )
        )
    await session.flush()
    await session.refresh(account)
    return Identity(account, [CANDIDATE_ROLE], None, None)


async def authenticate(session: AsyncSession, email: str, password: str) -> Identity:
    """Vérifie e-mail + mot de passe ; 401 INVALID_CREDENTIALS, 403 ACCOUNT_DISABLED."""
    account = await session.scalar(select(UserAccount).where(UserAccount.email == email))
    usable = account is not None and account.anonymized_at is None
    if not verify_password(password, account.password_hash if usable else None):
        raise AppError(ErrorCode.INVALID_CREDENTIALS)
    assert account is not None
    if account.account_status == "disabled":
        raise AppError(ErrorCode.ACCOUNT_DISABLED)
    if needs_rehash(account.password_hash):
        account.password_hash = hash_password(password)
    account.last_login_at = now_utc()
    identity = await load_identity(session, account.id)
    assert identity is not None
    return identity


async def issue_tokens(
    session: AsyncSession,
    settings: Settings,
    identity: Identity,
    family_id: uuid.UUID | None = None,
) -> tuple[IssuedTokens, RefreshToken]:
    """Jeton d'accès + nouveau jeton de renouvellement (nouvelle famille par défaut)."""
    access = create_access_token(
        settings,
        user_id=identity.account.id,
        account_type=identity.account.account_type,
        roles=identity.roles,
        candidate_id=identity.candidate_id,
        institution_id=identity.institution_id,
    )
    refresh = new_opaque_token()
    now = now_utc()
    row = RefreshToken(
        user_id=identity.account.id,
        family_id=family_id or uuid.uuid4(),
        token_hash=hash_opaque_token(refresh),
        expires_at=now + timedelta(days=settings.refresh_token_ttl_days),
        created_at=now,
    )
    session.add(row)
    await session.flush()
    return IssuedTokens(access, settings.access_token_ttl_s, refresh), row


async def refresh(session: AsyncSession, settings: Settings, token: str | None) -> IssuedTokens:
    """Rotation du jeton de renouvellement ; rôles relus en base (SA-5 §4)."""
    if not token:
        raise AppError(ErrorCode.UNAUTHENTICATED, details={"reason": "no_refresh_token"})
    row = await session.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_opaque_token(token))
        .with_for_update()
    )
    now = now_utc()
    if row is None:
        raise AppError(ErrorCode.UNAUTHENTICATED, details={"reason": "invalid_refresh_token"})
    if row.replaced_by_id is not None or row.revoked_at is not None:
        if row.replaced_by_id is not None:
            # Jeton déjà échangé et présenté de nouveau : on coupe toute la famille.
            await revoke_family(session, row.family_id, now)
            await session.commit()
        raise AppError(ErrorCode.UNAUTHENTICATED, details={"reason": "refresh_token_reused"})
    if row.expires_at <= now:
        raise AppError(ErrorCode.UNAUTHENTICATED, details={"reason": "refresh_token_expired"})

    identity = await load_identity(session, row.user_id)
    if identity is None or identity.account.anonymized_at is not None:
        raise AppError(ErrorCode.UNAUTHENTICATED, details={"reason": "unknown_user"})
    if identity.account.account_status == "disabled":
        await revoke_family(session, row.family_id, now)
        await session.commit()
        raise AppError(ErrorCode.ACCOUNT_DISABLED)

    issued, new_row = await issue_tokens(session, settings, identity, family_id=row.family_id)
    row.revoked_at = now
    row.replaced_by_id = new_row.id
    await session.commit()
    return issued


async def revoke_family(session: AsyncSession, family_id: uuid.UUID, now: datetime) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
        .execution_options(synchronize_session=False)
    )


async def logout(session: AsyncSession, user_id: uuid.UUID, token: str | None) -> None:
    """Révoque la famille du jeton de renouvellement présenté (s'il appartient à l'appelant)."""
    if not token:
        return
    row = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_opaque_token(token))
    )
    if row is not None and row.user_id == user_id:
        await revoke_family(session, row.family_id, now_utc())
        await session.commit()


async def user_exists(session: AsyncSession, user_id: uuid.UUID) -> bool:
    return (await session.scalar(select(func.count()).where(UserAccount.id == user_id))) == 1
