"""Outils d'agent déterministes (SA-21) : get_fees, get_admission_conditions, check_eligibility.

Appelés directement (comme l'orchestrateur E4), sans HTTP ni LLM.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.schemas.admission import BacProfile
from app.services.catalogue.admission import evaluate_condition
from app.tools import catalogue_tools as tools
from tests.api.conftest import World

pytestmark = pytest.mark.db

D = date(2026, 11, 17)


@pytest.fixture
async def published(world: World):
    """Condition 2026-2027 : séries maths/techniques/informatique, moyenne ≥ 12,
    mathématiques ≥ 11, physique ≥ 10 ; test exigé."""
    cond = await world.condition(
        "2026-2027", "published", grades={"mathematiques": "11", "physique": "10"}
    )
    fee = await world.fee("2026-2027", "published")
    await world.commit()
    return cond, fee


async def eligibility(session, w: World, **profile):
    params = tools.CheckEligibilityInput(
        programme_code=w.programme_code,
        academic_year="2026-2027",
        as_of=D,
        profile=BacProfile(**profile),
    )
    return await tools.check_eligibility(session, params)


async def test_profil_eligible(world: World, db_session, published):
    cond, _ = published
    res = await eligibility(
        db_session,
        world,
        bac_section="mathematiques",
        bac_average="14.5",
        subject_grades={"mathematiques": "15", "physique": "12.25"},
    )
    assert res.ok is True
    data = res.data
    assert data.status == "met"
    [verdict] = data.verdicts
    assert verdict.source.entity_id == cond.id
    assert verdict.source.version == 1
    assert verdict.source.valid_from == date(2026, 3, 1)
    assert "Test (QCM) de positionnement." in verdict.next_steps
    assert {c.criterion for c in data.criteria} == {
        "required_diploma",
        "bac_section",
        "min_average",
        "subject_grade:mathematiques",
        "subject_grade:physique",
    }
    assert data.missing_information == []


async def test_profil_mauvaise_serie(world: World, db_session, published):
    res = await eligibility(
        db_session,
        world,
        bac_section="lettres",
        bac_average="16",
        subject_grades={"mathematiques": "12", "physique": "12"},
    )
    assert res.data.status == "not_met"
    section = next(c for c in res.data.criteria if c.criterion == "bac_section")
    assert section.status == "not_met"
    assert "lettres" in section.explanation


async def test_profil_moyenne_et_note_insuffisantes(world: World, db_session, published):
    res = await eligibility(
        db_session,
        world,
        bac_section="sciences_techniques",
        bac_average="11.50",
        subject_grades={"mathematiques": "9", "physique": "13"},
    )
    assert res.data.status == "not_met"
    by = {c.criterion: c for c in res.data.criteria}
    assert by["min_average"].status == "not_met"
    assert by["min_average"].expected == "12.00" and by["min_average"].actual == "11.50"
    assert by["subject_grade:mathematiques"].status == "not_met"
    assert by["subject_grade:physique"].status == "met"


async def test_profil_incomplet(world: World, db_session, published):
    res = await eligibility(
        db_session, world, bac_section="mathematiques", subject_grades={"mathematiques": "14"}
    )
    assert res.data.status == "unknown"
    assert res.data.missing_information == ["bac_average", "subject_grades.physique"]
    unknown = [c for c in res.data.criteria if c.status == "unknown"]
    assert all(c.met is None for c in unknown)


async def test_aucune_condition_publiee(world: World, db_session, published):
    params = tools.CheckEligibilityInput(
        programme_code=world.programme_code,
        academic_year="2026-2027",
        as_of=D,
        profile=BacProfile(applicant_category="transfer_student", entry_level=2),
    )
    res = await tools.check_eligibility(db_session, params)
    assert res.data.status == "no_official_condition"


async def test_annee_manquante_erreur_structuree(world: World, db_session, published):
    res = await tools.get_fees(
        db_session, tools.GetFeesInput(programme_code=world.programme_code, as_of=D)
    )
    assert res.ok is False
    assert res.code == "ACADEMIC_YEAR_REQUIRED"
    assert res.details == {"available_academic_years": ["2026-2027"]}

    res = await tools.get_admission_conditions(
        db_session, tools.GetAdmissionConditionsInput(programme_id=world.programme, as_of=D)
    )
    assert res.ok is False and res.code == "ACADEMIC_YEAR_REQUIRED"

    res = await eligibility(db_session, world, bac_section="mathematiques")
    assert res.ok is True  # l'année est fournie dans `eligibility`


async def test_get_fees_par_code(world: World, db_session, published):
    _, fee = published
    res = await tools.get_fees(
        db_session,
        tools.GetFeesInput(
            programme_code=world.programme_code,
            speciality_code="GL",
            academic_year="2026-2027",
            as_of=D,
        ),
    )
    assert res.ok is True
    [f] = res.data.fee_schedules
    assert f.id == fee.id
    assert f.annual_total.amount == "6800.000"  # colonne générée, pas de calcul côté outil
    assert f.source.entity_type == "fee_schedule"

    res = await tools.get_fees(
        db_session,
        tools.GetFeesInput(programme_code="INCONNU", academic_year="2026-2027", as_of=D),
    )
    assert res.ok is False and res.code == "NOT_FOUND"


async def test_get_admission_conditions(world: World, db_session, published):
    cond, _ = published
    res = await tools.get_admission_conditions(
        db_session,
        tools.GetAdmissionConditionsInput(
            programme_code=world.programme_code, academic_year="2026-2027", as_of=D
        ),
    )
    assert res.ok is True
    [c] = res.data.conditions
    assert c.id == cond.id
    assert [r.subject_key for r in c.subject_requirements] == ["mathematiques", "physique"]


def test_specs_pour_e4():
    names = [s["name"] for s in tools.TOOL_SPECS]
    assert names == ["get_fees", "get_admission_conditions", "check_eligibility"]
    for spec in tools.TOOL_SPECS:
        assert spec["kind"] == "deterministic"
        assert spec["input_schema"]["type"] == "object"


async def test_evaluation_pure_diplome_superieur(world: World, db_session, published):
    """Un titulaire d'une licence satisfait l'exigence « baccalauréat » (rang supérieur)."""
    cond, _ = published
    status, criteria, _, _ = evaluate_condition(
        cond,
        [],
        BacProfile(highest_diploma="licence", bac_section="mathematiques", bac_average="13"),
    )
    assert status == "met"
    assert criteria[0].criterion == "required_diploma" and criteria[0].status == "met"
