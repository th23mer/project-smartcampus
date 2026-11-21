"""Scénario de bout en bout sur les données de démo SA-18 (SA-22).

Le seed de démonstration est chargé dans `db-test` une fois par session (fixture `demo_seed`,
même script que `make seed`, partagée avec tests/test_seed.py), puis :

1. un responsable IIT (compte démo A) crée une grille de frais 2027-2028 pour LIC-INFO, la
   soumet ; ni lui ni l'admin ne peuvent la publier ; le second responsable IIT (B) la publie ;
2. le visiteur la voit via l'API publique et l'agent via l'outil `get_fees` (carte source) ;
   la trace de publication est complète (status_history, catalogue_audit_log) ;
3. `check_eligibility` sur les 3 candidats fictifs donne les verdicts attendus du PDF SA-18
   (profils lus en base, rentrée 2027-2028).

Les écritures du scénario sont annulées (transaction du test) ; en fin de session, db-test est
remise à vide (`downgrade base` + `upgrade head`).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AcademicRecord, AcademicRecordSubject, CandidateProfile, Programme, enums
from app.schemas.admission import BacProfile
from app.tools.catalogue_tools import (
    CheckEligibilityInput,
    GetFeesInput,
    check_eligibility,
    get_fees,
)

pytestmark = pytest.mark.db

BACKEND_DIR = Path(__file__).resolve().parents[2]
D = "2026-11-17"  # date de la démo (SA-18)
YEAR = "2027-2028"


def _seed_uuid(n: int) -> str:
    return f"5eed0000-0000-4000-8000-{n:012d}"


IIT = _seed_uuid(1001)
LEAD_A, LEAD_B, ADMIN = _seed_uuid(1), _seed_uuid(2), _seed_uuid(6)
C1, C2, C3 = _seed_uuid(101), _seed_uuid(102), _seed_uuid(103)


def h(user: str, roles: str, institution: str | None = None) -> dict[str, str]:
    out = {"X-Dev-User-Id": user, "X-Dev-Roles": roles}
    if institution:
        out["X-Dev-Institution-Id"] = institution
    return out


H_A = h(LEAD_A, "iit_academic_lead", IIT)
H_B = h(LEAD_B, "iit_academic_lead", IIT)
H_ADMIN = h(ADMIN, "platform_admin")


@pytest.fixture(scope="module")
def seeded(demo_seed: dict) -> None:
    """Seed SA-18 chargé une fois par session (fixture `demo_seed`, partagée avec
    tests/test_seed.py) ; db-test est remise à vide en fin de session."""


async def programme_id(session: AsyncSession, code: str) -> uuid.UUID:
    pid = await session.scalar(select(Programme.id).where(Programme.code == code))
    assert pid is not None, code
    return pid


# --- 1 et 2 : grille 2027-2028, quatre yeux, lecture publique et outil -----------------------


async def test_grille_2027_2028_de_la_redaction_a_l_agent(seeded, api, db_session: AsyncSession):
    lic = await programme_id(db_session, "LIC-INFO")

    # Avant : 2027-2028 n'est pas officielle (seed : grille en relecture seulement).
    before = await get_fees(db_session, GetFeesInput(programme_code="LIC-INFO", as_of=D))  # type: ignore[arg-type]
    assert before.ok is False and before.code == "ACADEMIC_YEAR_REQUIRED"
    assert before.details == {"available_academic_years": ["2026-2027"]}

    # Rédaction par A (brouillon) + plan de paiement en 2 tranches.
    body = {
        "programme_id": str(lic),
        "academic_year": YEAR,
        "registration_fee": {"amount": "310.000", "currency": "TND"},
        "tuition_fee": {"amount": "6450.000", "currency": "TND"},
        "other_fees": {"amount": "150.000", "currency": "TND"},
        "other_fees_label_fr": "Assurance et carte d'étudiant (fictif)",
        "valid_from": "2026-11-01",
        "notes_fr": "Grille 2027-2028 (démo SA-22, fictive).",
    }
    r = await api.post("/staff/catalogue/fee-schedules", json=body, headers=H_A)
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert r.json()["publication_status"] == "draft"
    plan = {
        "fee_schedule_id": rid,
        "code": "TRANCHES-2",
        "label_fr": "Deux tranches",
        "installment_count": 2,
        "is_default": True,
        "installments": [
            {"installment_no": 1, "due_label_fr": "À l'inscription", "amount": "3455.000"},
            {"installment_no": 2, "due_date": "2028-01-15", "amount": "3455.000"},
        ],
    }
    r = await api.post("/staff/catalogue/payment-plans", json=plan, headers=H_A)
    assert r.status_code == 201, r.text

    # Soumission par A.
    etag = (await api.get(f"/staff/catalogue/fee-schedules/{rid}", headers=H_A)).headers["ETag"]
    r = await api.post(
        f"/staff/catalogue/fee-schedules/{rid}/submit", headers=H_A | {"If-Match": etag}
    )
    assert r.status_code == 200, r.text
    etag = r.headers["ETag"]

    # A ne publie pas ce qu'il a soumis ; l'admin ne publie jamais (D-B, D-H).
    r = await api.post(
        f"/staff/catalogue/fee-schedules/{rid}/publish", headers=H_A | {"If-Match": etag}
    )
    assert (r.status_code, r.json()["error"]["code"]) == (403, "FOUR_EYES_REQUIRED")
    r = await api.post(
        f"/staff/catalogue/fee-schedules/{rid}/publish", headers=H_ADMIN | {"If-Match": etag}
    )
    assert (r.status_code, r.json()["error"]["code"]) == (403, "FORBIDDEN")
    # Tant qu'elle est en relecture, rien n'est visible publiquement.
    r = await api.get(
        f"/catalogue/programmes/{lic}/fees", params={"academic_year": YEAR, "date": D}
    )
    assert rid not in r.text

    # B publie.
    r = await api.post(
        f"/staff/catalogue/fee-schedules/{rid}/publish", headers=H_B | {"If-Match": etag}
    )
    assert r.status_code == 200, r.text
    assert (r.json()["submitted_by"], r.json()["published_by"]) == (LEAD_A, LEAD_B)

    # Le visiteur la voit (API publique, sans authentification).
    r = await api.get(
        f"/catalogue/programmes/{lic}/fees", params={"academic_year": YEAR, "date": D}
    )
    assert r.status_code == 200, r.text
    data = r.json()
    [fee] = [f for f in data["fee_schedules"] if f["id"] == rid]
    assert fee["annual_total"] == {"amount": "6910.000", "currency": "TND"}
    assert fee["source"]["entity_type"] == "fee_schedule"
    assert fee["source"]["valid_from"] == "2026-11-01"
    assert data["available_academic_years"] == ["2026-2027", YEAR]

    # L'agent la voit via l'outil déterministe get_fees (même service).
    out = await get_fees(
        db_session,
        GetFeesInput(programme_code="LIC-INFO", academic_year=YEAR, as_of=D),  # type: ignore[arg-type]
    )
    assert out.ok is True
    tool_fee = next(f for f in out.data.fee_schedules if str(f.id) == rid)
    assert tool_fee.annual_total.amount == "6910.000"
    assert str(tool_fee.source.entity_id) == rid
    out = await get_fees(db_session, GetFeesInput(programme_code="LIC-INFO", as_of=D))  # type: ignore[arg-type]
    assert out.ok is False and out.details == {"available_academic_years": ["2026-2027", YEAR]}

    # Traçabilité : transitions et auteurs (status_history, catalogue_audit_log).
    hist = (
        await db_session.execute(
            text(
                "SELECT from_status, to_status, actor_user_id::text, requires_human "
                "FROM status_history WHERE entity_type = 'fee_schedule' AND entity_id = :id "
                "ORDER BY changed_at, to_status"
            ),
            {"id": rid},
        )
    ).all()
    assert [tuple(row) for row in hist] == [
        ("draft", "pending_review", LEAD_A, False),
        ("pending_review", "published", LEAD_B, True),
    ]
    actions = (
        await db_session.execute(
            text(
                "SELECT action, actor_id::text FROM catalogue_audit_log "
                "WHERE table_name = 'fee_schedule' AND row_id = :id"
            ),
            {"id": rid},
        )
    ).all()
    assert ("publish", LEAD_B) in {tuple(a) for a in actions}
    assert ("submit", LEAD_A) in {tuple(a) for a in actions}


# --- 3 : check_eligibility sur les 3 candidats fictifs --------------------------------------


async def bac_profile(session: AsyncSession, user_id: str, **overrides: Any) -> BacProfile:
    """Profil scolaire du candidat lu en base (relevé de bac du seed)."""
    record = await session.scalar(
        select(AcademicRecord)
        .join(CandidateProfile, CandidateProfile.id == AcademicRecord.candidate_profile_id)
        .where(CandidateProfile.user_id == uuid.UUID(user_id), AcademicRecord.record_type == "bac")
    )
    assert record is not None
    subjects = await session.execute(
        select(AcademicRecordSubject.subject_key, AcademicRecordSubject.grade).where(
            AcademicRecordSubject.academic_record_id == record.id
        )
    )
    grades = {k: g for k, g in subjects if k in enums.BAC_SUBJECT_KEY and g is not None}
    return BacProfile(
        bac_section=record.bac_section,
        bac_average=record.overall_average,
        subject_grades=grades,
        **overrides,
    )


#: Licence en cours (L1 + L2 validées ailleurs, moyenne de L2 = 10,90) : profil C3 pour
#: l'entrée en cycle ingénieur et la réorientation en 2e année de Licence.
C3_UNIVERSITY = {
    "highest_diploma": "other_higher_education",
    "validated_years": 2,
    "last_year_average": Decimal("10.90"),
}

#: (candidat, formation, surcharges du profil, verdict attendu) : tableau de la section 4 du PDF
#: SA-18 ; LIC-GC (relecture) et LIC-MECA (brouillon) n'ont pas de condition 2027-2028 officielle.
ELIGIBILITY = [
    ("C1", "LIC-INFO", {}, "met"),
    ("C1", "PREPA-MP", {}, "met"),
    ("C1", "PREPA-PT", {}, "met"),
    ("C1", "LIC-ELEC", {}, "met"),
    ("C1", "LIC-GEST", {}, "met"),
    ("C1", "LIC-COMM", {}, "met"),
    ("C1", "LIC-GC", {}, "no_official_condition"),
    ("C1", "LIC-MECA", {}, "no_official_condition"),
    ("C2", "LIC-INFO", {}, "not_met"),
    ("C2", "PREPA-MP", {}, "not_met"),
    ("C2", "LIC-ELEC", {}, "not_met"),
    ("C2", "LIC-GEST", {}, "met"),
    ("C2", "LIC-COMM", {}, "met"),
    ("C3", "PREPA-PT", {}, "met"),
    ("C3", "LIC-ELEC", {}, "met"),
    ("C3", "LIC-INFO", {}, "met"),
    ("C3", "LIC-GEST", {}, "met"),
    ("C3", "PREPA-MP", {}, "not_met"),
    (
        "C3",
        "ING",
        {"applicant_category": "higher_education_graduate", "entry_level": 1, **C3_UNIVERSITY},
        "not_met",
    ),
    (
        "C3",
        "LIC-INFO",
        {"applicant_category": "transfer_student", "entry_level": 2, **C3_UNIVERSITY},
        "met",
    ),
]
_IDS = {"C1": C1, "C2": C2, "C3": C3}


@pytest.mark.parametrize(
    ("candidate", "code", "overrides", "expected"),
    ELIGIBILITY,
    ids=[f"{c}-{p}{'-' + o['applicant_category'] if o else ''}" for c, p, o, _ in ELIGIBILITY],
)
async def test_check_eligibility_candidats_demo(
    seeded, db_session: AsyncSession, candidate: str, code: str, overrides: dict, expected: str
):
    profile = await bac_profile(db_session, _IDS[candidate], **overrides)
    out = await check_eligibility(
        db_session,
        CheckEligibilityInput(programme_code=code, academic_year=YEAR, as_of=D, profile=profile),  # type: ignore[arg-type]
    )
    assert out.ok is True, out
    result = out.data
    assert result.status == expected, [
        (c.criterion, c.status, c.expected, c.actual) for c in result.criteria
    ]
    assert result.computed_by == "code"
    if expected == "not_met":
        # Le verdict est expliqué : au moins un critère KO avec attendu et constaté.
        assert any(c.status == "not_met" and c.explanation for c in result.criteria)
    if expected in ("met", "not_met"):
        assert all(v.source.entity_type == "admission_condition" for v in result.verdicts)


async def test_eligibilite_explications_c2_et_c3(seeded, db_session: AsyncSession):
    """Raisons attendues du PDF SA-18 : C2 série non acceptée ; C3 moyenne 11,40 < 12."""
    c2 = await check_eligibility(
        db_session,
        CheckEligibilityInput(
            programme_code="LIC-INFO",
            academic_year=YEAR,
            as_of=D,  # type: ignore[arg-type]
            profile=await bac_profile(db_session, C2),
        ),
    )
    failed = {c.criterion for c in c2.data.criteria if c.status == "not_met"}
    assert "bac_section" in failed
    c3 = await check_eligibility(
        db_session,
        CheckEligibilityInput(
            programme_code="PREPA-MP",
            academic_year=YEAR,
            as_of=D,  # type: ignore[arg-type]
            profile=await bac_profile(db_session, C3),
        ),
    )
    avg = next(c for c in c3.data.criteria if c.criterion == "min_average")
    assert (avg.status, avg.expected, avg.actual) == ("not_met", "12.00", "11.40")
