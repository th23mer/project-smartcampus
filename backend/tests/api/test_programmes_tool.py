"""Tests SA-20 : outils d'agent `search_catalogue` et `explore_paths_from` (sans LLM)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.tools.search_catalogue import (
    TOOLS,
    ExplorePathsInput,
    SearchCatalogueInput,
    explore_paths_from,
    search_catalogue,
)
from tests.api.conftest import World
from tests.api.test_programmes import add_bridge, add_programme

pytestmark = pytest.mark.db


async def test_search_catalogue_par_specialite_et_source(db_session: AsyncSession, world: World):
    w = world
    await add_programme(w, f"ING-{w.tag}", "Cycle ingénieur (fictif)", ptype="engineering")
    await add_programme(w, f"BR-{w.tag}", "Licence brouillon logiciel", status="draft")
    out = await search_catalogue(
        db_session, SearchCatalogueInput(query="génie LOGICIEL", institution=f"T{w.tag}")
    )
    assert out.total == 1 and not out.truncated
    hit = out.results[0]
    assert hit.programme_id == w.programme and hit.level == "licence"
    assert [s.code for s in hit.matched_specialities] == ["GL"]
    assert hit.source.entity_type == "programme" and hit.source.entity_id == w.programme
    assert hit.api_path == f"/api/v1/catalogue/programmes/{w.programme}"

    by_level = await search_catalogue(
        db_session, SearchCatalogueInput(institution=f"T{w.tag}", level="prepa")
    )
    assert by_level.total == 0
    limited = await search_catalogue(
        db_session, SearchCatalogueInput(institution=f"T{w.tag}", limit=1)
    )
    assert limited.total == 2 and len(limited.results) == 1 and limited.truncated


async def test_search_catalogue_erreurs_structurees(db_session: AsyncSession, world: World):
    with pytest.raises(AppError) as info:
        await search_catalogue(db_session, SearchCatalogueInput(level="doctorat"))
    assert info.value.code == "VALIDATION_ERROR"
    with pytest.raises(ValueError):
        SearchCatalogueInput(limit=500)


async def test_explore_paths_from_duree_calculee(db_session: AsyncSession, world: World):
    w = world
    prepa = await add_programme(
        w, f"PREPA-{w.tag}", "Prépa intégrée (fictive)", ptype="preparatory", duration=2
    )
    eng = await add_programme(
        w, f"ING-{w.tag}", "Cycle ingénieur (fictif)", ptype="engineering", duration=3
    )
    lic = await add_programme(w, f"LIC2-{w.tag}", "Licence (fictive)", duration=3)
    await add_bridge(w, prepa.id, eng.id, entry=1, after=2)  # 2 + 3 = 5 ans
    await add_bridge(w, prepa.id, lic.id, entry=2, after=1)  # 1 + (3 - 2 + 1) = 3 ans
    await add_bridge(w, prepa.id, w.programme, entry=1, after=2, status="draft")

    out = await explore_paths_from(db_session, ExplorePathsInput(programme_code=prepa.code))
    assert out.from_programme.id == prepa.id
    assert [(o.to_programme.code, o.total_duration_years) for o in out.options] == [
        (lic.code, 3),
        (eng.code, 5),
    ]
    assert all(o.source.entity_type == "bridge" for o in out.options)

    with pytest.raises(AppError) as info:
        await explore_paths_from(db_session, ExplorePathsInput(programme_code="INCONNU"))
    assert info.value.code == "NOT_FOUND"
    with pytest.raises(AppError) as info:
        await explore_paths_from(db_session, ExplorePathsInput(programme_id=uuid.uuid4()))
    assert info.value.code == "NOT_FOUND"
    with pytest.raises(AppError) as info:
        await explore_paths_from(db_session, ExplorePathsInput())
    assert info.value.code == "VALIDATION_ERROR"


def test_contrats_json_schema():
    """Les schémas d'entrée sont exportables pour la déclaration des outils (E4)."""
    for name, (_fn, inp, out, description) in TOOLS.items():
        schema = inp.model_json_schema()
        assert schema["type"] == "object" and schema.get("additionalProperties") is False, name
        assert out.model_json_schema()["type"] == "object"
        assert description
