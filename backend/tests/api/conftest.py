"""Fixtures des tests d'API et de services du catalogue (SA-21 ; réutilisables par SA-20).

Base réelle `db-test` (SA-16), rôle applicatif `smartcampus_app`. Chaque test tourne dans
**une transaction externe annulée à la fin** : les sessions des requêtes HTTP sont liées à
la même connexion en mode `create_savepoint`, donc leurs `commit()` ne valident qu'un
savepoint. Rien ne reste en base après le test.

Lancement (une seule session pytest à la fois sur db-test) :

    set -a; . ../.env; set +a
    flock <scratchpad>/db-test.lock ~/.local/bin/uv run pytest tests/api tests/services
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.db import get_session
from app.models import (
    AdmissionCondition,
    AdmissionSubjectRequirement,
    FeeSchedule,
    Institution,
    PaymentInstallment,
    PaymentPlan,
    Programme,
    Speciality,
    UserAccount,
)
from tests.conftest import shared_app

pytestmark = pytest.mark.db


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} non définie (base de test SA-16 requise)")
    return value


@pytest.fixture(scope="session")
def api_migrated(test_db_schema: str) -> str:
    """Schéma à jour : fixture de session commune `test_db_schema` (une seule remise à zéro
    par session, SA-22)."""
    return _env("TEST_DATABASE_URL")


@pytest.fixture
async def db_conn(api_migrated: str) -> AsyncIterator[AsyncConnection]:
    """Connexion dans une transaction externe annulée à la fin du test."""
    engine = create_async_engine(api_migrated, poolclass=NullPool)
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            yield conn
        finally:
            await trans.rollback()
    await engine.dispose()


def _session(conn: AsyncConnection) -> AsyncSession:
    return AsyncSession(
        bind=conn,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
        autoflush=False,
    )


@pytest.fixture
async def db_session(db_conn: AsyncConnection) -> AsyncIterator[AsyncSession]:
    """Session des tests (préparation des données, appels directs aux services/outils)."""
    session = _session(db_conn)
    try:
        yield session
    finally:
        await session.close()


async def _auto_idempotency_key(request: httpx.Request) -> None:
    """Comme le client du front (SA-8) : une clé neuve par POST/PUT/PATCH/DELETE (SA-5 D8)."""
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        request.headers.setdefault("Idempotency-Key", str(uuid.uuid4()))


def make_client(db_conn: AsyncConnection, *, auto_idempotency: bool = True) -> httpx.AsyncClient:
    """Client HTTP sur l'application, une session neuve par requête (comme en production),
    toutes liées à la connexion du test (y compris celles du middleware d'idempotence)."""
    app = shared_app()

    async def _override() -> AsyncIterator[AsyncSession]:
        session = _session(db_conn)
        try:
            yield session
        finally:
            await session.close()

    app.dependency_overrides[get_session] = _override
    hooks = {"request": [_auto_idempotency_key]} if auto_idempotency else {}
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test/api/v1",
        event_hooks=hooks,
    )


@pytest.fixture
async def api(db_conn: AsyncConnection) -> AsyncIterator[httpx.AsyncClient]:
    """Client HTTP qui ajoute une `Idempotency-Key` neuve à chaque écriture (SA-22)."""
    async with make_client(db_conn) as client:
        yield client


@pytest.fixture
async def api_raw(db_conn: AsyncConnection) -> AsyncIterator[httpx.AsyncClient]:
    """Client HTTP sans clé automatique (tests de l'idempotence, SA-22)."""
    async with make_client(db_conn, auto_idempotency=False) as client:
        yield client


# --- Jeu de données synthétique ------------------------------------------------------------------


def headers(*roles: str, user: uuid.UUID, institution: uuid.UUID | None = None) -> dict[str, str]:
    """En-têtes de l'auth simulée (SA-7)."""
    out = {"X-Dev-User-Id": str(user), "X-Dev-Roles": ",".join(roles)}
    if institution:
        out["X-Dev-Institution-Id"] = str(institution)
    return out


@dataclass
class World:
    """Données fictives : 2 institutions, 2 responsables IIT (4 yeux), 1 ISB, direction, admin,
    candidat ; une formation IIT publiée avec une spécialité publiée."""

    session: AsyncSession
    tag: str
    iit: uuid.UUID = field(default=uuid.UUID(int=0))
    isb: uuid.UUID = field(default=uuid.UUID(int=0))
    lead_a: uuid.UUID = field(default=uuid.UUID(int=0))
    lead_b: uuid.UUID = field(default=uuid.UUID(int=0))
    isb_lead: uuid.UUID = field(default=uuid.UUID(int=0))
    direction: uuid.UUID = field(default=uuid.UUID(int=0))
    admin: uuid.UUID = field(default=uuid.UUID(int=0))
    candidate: uuid.UUID = field(default=uuid.UUID(int=0))
    programme: uuid.UUID = field(default=uuid.UUID(int=0))
    programme_code: str = ""
    speciality: uuid.UUID = field(default=uuid.UUID(int=0))
    isb_programme: uuid.UUID = field(default=uuid.UUID(int=0))

    # En-têtes prêts à l'emploi
    def h_lead_a(self) -> dict[str, str]:
        return headers("iit_academic_lead", user=self.lead_a, institution=self.iit)

    def h_lead_b(self) -> dict[str, str]:
        return headers("iit_academic_lead", user=self.lead_b, institution=self.iit)

    def h_isb(self) -> dict[str, str]:
        return headers("isb_academic_lead", user=self.isb_lead, institution=self.isb)

    def h_direction(self) -> dict[str, str]:
        return headers("direction", user=self.direction)

    def h_admin(self) -> dict[str, str]:
        return headers("platform_admin", user=self.admin)

    def h_candidate(self) -> dict[str, str]:
        return headers("candidate", user=self.candidate)

    # --- Fabriques ---------------------------------------------------------------------------
    async def user(self, label: str, account_type: str = "staff") -> uuid.UUID:
        account = UserAccount(
            email=f"{label}-{self.tag}@demo.local",
            password_hash="x",
            full_name=f"Compte fictif {label}",
            account_type=account_type,
            account_status="active",
        )
        self.session.add(account)
        await self.session.flush()
        return account.id

    def _published(self, valid_from: str = "2020-09-01", valid_to: str | None = None) -> dict:
        return {
            "publication_status": "published",
            "valid_from": date.fromisoformat(valid_from),
            "valid_to": date.fromisoformat(valid_to) if valid_to else None,
            "created_by": self.lead_a,
            "submitted_by": self.lead_a,
            "submitted_at": datetime(2026, 1, 1, tzinfo=UTC),
            "published_by": self.lead_b,
            "published_at": datetime(2026, 1, 2, tzinfo=UTC),
        }

    def publication(
        self,
        status: str,
        valid_from: str = "2026-03-01",
        valid_to: str | None = None,
        published_at: datetime | None = None,
        **overrides: Any,
    ) -> dict[str, Any]:
        """Bloc de publication cohérent avec `status` (R soumet, U publie) + surcharges."""
        cols: dict[str, Any] = {
            "publication_status": status,
            "valid_from": date.fromisoformat(valid_from) if valid_from else None,
            "valid_to": date.fromisoformat(valid_to) if valid_to else None,
            "created_by": self.lead_a,
        }
        if status in ("pending_review", "published", "archived"):
            cols |= {"submitted_by": self.lead_a, "submitted_at": datetime(2026, 2, 1, tzinfo=UTC)}
        if status in ("published", "archived"):
            cols |= {
                "published_by": self.lead_b,
                "published_at": published_at or datetime(2026, 2, 2, tzinfo=UTC),
            }
        return cols | overrides

    async def fee(
        self,
        academic_year: str = "2026-2027",
        status: str = "published",
        *,
        speciality: uuid.UUID | None = None,
        study_year: int | None = None,
        tuition: str = "6500",
        registration: str = "300",
        plans: bool = True,
        programme: uuid.UUID | None = None,
        **pub: Any,
    ) -> FeeSchedule:
        row = FeeSchedule(
            programme_id=programme or self.programme,
            speciality_id=speciality,
            study_year=study_year,
            student_category="tunisian",
            academic_year=academic_year,
            currency="TND",
            registration_fee=Decimal(registration),
            annual_tuition_fee=Decimal(tuition),
            other_fees=Decimal("0"),
            **self.publication(status, **pub),
        )
        self.session.add(row)
        await self.session.flush()
        if plans:
            total = Decimal(registration) + Decimal(tuition)
            plan = PaymentPlan(
                fee_schedule_id=row.id,
                code="TRANCHES-2",
                label_fr="Deux tranches",
                installment_count=2,
                discount_rate=Decimal("0"),
                is_default=True,
            )
            self.session.add(plan)
            await self.session.flush()
            half = (total / 2).quantize(Decimal("0.001"))
            for no, (label, amount) in enumerate(
                [("À l'inscription", half), ("Janvier", total - half)], start=1
            ):
                self.session.add(
                    PaymentInstallment(
                        payment_plan_id=plan.id,
                        installment_no=no,
                        due_label_fr=label,
                        amount=amount,
                    )
                )
            await self.session.flush()
        return row

    async def condition(
        self,
        academic_year: str = "2026-2027",
        status: str = "published",
        *,
        speciality: uuid.UUID | None = None,
        sections: list[str] | None = None,
        min_average: str | None = "12",
        grades: dict[str, str] | None = None,
        programme: uuid.UUID | None = None,
        **pub: Any,
    ) -> AdmissionCondition:
        row = AdmissionCondition(
            programme_id=programme or self.programme,
            speciality_id=speciality,
            entry_level=1,
            applicant_category="new_bachelor",
            required_diploma="baccalaureate",
            accepted_bac_sections=sections
            if sections is not None
            else ["mathematiques", "sciences_techniques", "sciences_informatique"],
            min_average=Decimal(min_average) if min_average else None,
            average_basis="bac_average" if min_average else None,
            requires_application_file=True,
            requires_test=True,
            requires_interview=False,
            academic_year=academic_year,
            summary_fr="Bac scientifique avec 12 de moyenne (fictif).",
            **self.publication(status, **pub),
        )
        self.session.add(row)
        await self.session.flush()
        for key, grade in (grades if grades is not None else {"mathematiques": "11"}).items():
            self.session.add(
                AdmissionSubjectRequirement(
                    admission_condition_id=row.id,
                    subject_key=key,
                    subject_name_fr=key.capitalize(),
                    min_grade=Decimal(grade),
                )
            )
        await self.session.flush()
        return row

    async def commit(self) -> None:
        await self.session.commit()


@pytest.fixture
async def world(db_session: AsyncSession) -> World:
    """Jeu de données de base, validé (savepoint) pour être vu par les requêtes HTTP."""
    s = db_session
    w = World(session=s, tag=uuid.uuid4().hex[:6].upper())
    await s.execute(text("SELECT 1"))
    w.lead_a = await w.user("resp-iit-a")
    w.lead_b = await w.user("resp-iit-b")
    w.isb_lead = await w.user("resp-isb")
    w.direction = await w.user("direction")
    w.admin = await w.user("admin")
    w.candidate = await w.user("candidat", "candidate")

    iit = Institution(code=f"T{w.tag}", name_fr="IIT (fictif)", city="Sfax", **w._published())
    isb = Institution(code=f"S{w.tag}", name_fr="ISB (fictif)", city="Sfax", **w._published())
    s.add_all([iit, isb])
    await s.flush()
    w.iit, w.isb = iit.id, isb.id

    prog = Programme(
        institution_id=iit.id,
        code=f"LIC-{w.tag}",
        name_fr="Licence informatique (fictive)",
        programme_type="licence",
        duration_years=3,
        **w._published(),
    )
    isb_prog = Programme(
        institution_id=isb.id,
        code=f"ISB-{w.tag}",
        name_fr="Licence gestion (fictive)",
        programme_type="licence",
        duration_years=3,
        **w._published(),
    )
    s.add_all([prog, isb_prog])
    await s.flush()
    w.programme, w.programme_code, w.isb_programme = prog.id, prog.code, isb_prog.id

    spec = Speciality(
        programme_id=prog.id, code="GL", name_fr="Génie logiciel (fictif)", **w._published()
    )
    s.add(spec)
    await s.flush()
    w.speciality = spec.id
    await s.commit()
    return w
