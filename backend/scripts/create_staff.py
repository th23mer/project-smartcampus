"""Créer un compte staff en local (SA-28) : jamais par l'inscription publique.

L'inscription publique (`POST /auth/register`) crée toujours un candidat. Les comptes des
responsables sont créés par ce script (ou, plus tard, par l'admin via `/admin/users`).
Le mot de passe est demandé au clavier (jamais en argument, jamais affiché).

    uv run python scripts/create_staff.py --email resp.iit@example.com \\
        --full-name "Responsable IIT" --roles iit_academic_lead

Rôles : iit_academic_lead, isb_academic_lead, interview_lead, direction, platform_admin
(cumulables, séparés par des virgules). Les rôles doivent exister (`make seed`).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import dispose_engine, get_sessionmaker
from app.core.passwords import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    hash_password,
)
from app.core.security import STAFF_ROLES
from app.models import Role, UserAccount, UserRole
from app.schemas.auth import normalize_email


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Créer un compte staff SmartCampus AI.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--full-name", required=True)
    parser.add_argument("--roles", required=True, help="ex. iit_academic_lead,interview_lead")
    return parser.parse_args(argv)


def ask_password() -> str:
    password = getpass.getpass(f"Mot de passe ({PASSWORD_MIN_LENGTH} caractères minimum) : ")
    if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        raise SystemExit(
            f"Erreur : {PASSWORD_MIN_LENGTH} à {PASSWORD_MAX_LENGTH} caractères attendus."
        )
    if getpass.getpass("Confirmer le mot de passe : ") != password:
        raise SystemExit("Erreur : les mots de passe ne correspondent pas.")
    return password


async def create_staff(email: str, full_name: str, roles: list[str], password: str) -> None:
    async with get_sessionmaker()() as session:
        if await session.scalar(select(UserAccount.id).where(UserAccount.email == email)):
            raise SystemExit("Erreur : un compte existe déjà avec cet e-mail.")
        role_rows = list(await session.scalars(select(Role).where(Role.code.in_(roles))))
        missing = sorted(set(roles) - {r.code for r in role_rows})
        if missing:
            raise SystemExit(f"Erreur : rôles absents du référentiel (make seed ?) : {missing}")
        account = UserAccount(
            email=email,
            password_hash=hash_password(password),
            full_name=full_name,
            account_type="staff",
            account_status="active",
        )
        session.add(account)
        await session.flush()
        session.add_all(UserRole(user_id=account.id, role_id=r.id) for r in role_rows)
        await session.commit()
    await dispose_engine()


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        email = normalize_email(args.email)
    except ValueError as exc:
        raise SystemExit(f"Erreur : {exc}") from exc
    roles = sorted({r.strip() for r in args.roles.split(",") if r.strip()})
    allowed = {str(r) for r in STAFF_ROLES}
    if not roles or set(roles) - allowed:
        raise SystemExit(f"Erreur : rôles staff attendus parmi {sorted(allowed)}.")
    if not get_settings().database_url:
        raise SystemExit("Erreur : DATABASE_URL n'est pas définie.")
    asyncio.run(create_staff(email, args.full_name.strip(), roles, ask_password()))
    print(f"Compte staff créé : {email} ({', '.join(roles)}).")


if __name__ == "__main__":
    main()
