"""Outils d'agent déterministes du catalogue des formations (SA-20, pour E4).

Deux outils, sans LLM, qui lisent **uniquement** des données publiées et valides à la date D
(mêmes services que `GET /catalogue/programmes` et `GET /catalogue/bridges`, SA-5 §2.1) :

- `search_catalogue(session, SearchCatalogueInput)` → `SearchCatalogueOutput` : recherche de
  formations par mots-clés (FR/AR, insensible aux accents), établissement, niveau, spécialité ;
- `explore_paths_from(session, ExplorePathsInput)` → `ExplorePathsOutput` (Path Explorer F3,
  « passerelles depuis X ») : passerelles officielles au départ d'une formation, avec la durée
  totale du parcours calculée par le code.

Contrat pour E4 :
- entrées et sorties = modèles Pydantic ci-dessous (`model_json_schema()` donne le schéma de
  l'outil à déclarer au LLM) ; aucun champ n'est inventé par l'outil ;
- chaque résultat porte `source` (carte source officielle : table, id, version, publication,
  validité) et `api_path` (fiche publique) : l'agent cite la source, il ne paraphrase pas
  les règles ;
- erreurs structurées : `AppError` au format SA-5 (`VALIDATION_ERROR` pour un niveau ou un tri
  inconnu, `NOT_FOUND` pour une formation de départ inconnue ou non publiée) ;
- `user` (facultatif) : identité de l'utilisateur servi ; ces lectures sont publiques, donc
  aucun droit supplémentaire n'est requis ni accordé.
"""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.core.pagination import PageParams
from app.core.security import CurrentUser
from app.models import Programme, Speciality
from app.schemas.catalogue_common import SourceRef
from app.schemas.programmes import AccessMode, ProgrammeRef, ProgrammeType, SpecialityRef
from app.services.catalogue import programmes as svc

API_PREFIX = "/api/v1"


# ============ search_catalogue ============


class SearchCatalogueInput(BaseModel):
    """Paramètres de `search_catalogue` (tous facultatifs, combinables)."""

    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(
        default=None,
        max_length=200,
        description="Mots-clés en français ou en arabe (ex. « génie logiciel », « إعلامية »). "
        "Chaque mot doit apparaître dans la formation ou une de ses spécialités.",
    )
    institution: str | None = Field(
        default=None, description="Code de l'établissement : IIT ou ISB.", examples=["IIT"]
    )
    level: str | None = Field(
        default=None,
        description="Niveau : preparatory (prepa), licence, engineering (ingenieur), master.",
        examples=["licence"],
    )
    speciality: str | None = Field(
        default=None, max_length=100, description="Code ou nom de spécialité (ex. GL)."
    )
    on_date: date | None = Field(
        default=None, description="Date de référence (défaut : aujourd'hui à Tunis)."
    )
    limit: int = Field(default=10, ge=1, le=25, description="Nombre maximal de résultats.")


class CatalogueHit(BaseModel):
    """Une formation officielle trouvée."""

    programme_id: uuid.UUID
    code: str
    name: str
    name_ar: str | None
    institution: str
    level: ProgrammeType
    diploma_name: str | None
    duration_years: int
    matched_specialities: list[SpecialityRef] = Field(
        description="Spécialités officielles qui correspondent au filtre ou aux mots-clés."
    )
    api_path: str = Field(description="Fiche publique de la formation.")
    source: SourceRef


class SearchCatalogueOutput(BaseModel):
    on_date: date
    total: int = Field(description="Nombre total de formations correspondantes.")
    results: list[CatalogueHit]
    truncated: bool = Field(description="Vrai si `total` dépasse `limit`.")


async def _matched_specialities(
    session: AsyncSession, programme_id: uuid.UUID, d: date, params: SearchCatalogueInput
) -> list[dict]:
    """Spécialités officielles de la formation qui correspondent à la requête ou au filtre."""
    terms = svc.tokens_of(params.query)
    spec_filter = params.speciality.strip() if params.speciality else None
    if not terms and not spec_filter:
        return []
    rows = (
        await session.scalars(
            select(Speciality)
            .where(Speciality.programme_id == programme_id, svc.official(Speciality, d))
            .order_by(Speciality.code)
        )
    ).all()
    out = []
    for s in rows:
        text = svc.fold(
            " ".join(
                filter(None, (s.code, s.name_fr, s.name_ar, s.description_fr, s.career_outcomes_fr))
            )
        )
        by_filter = spec_filter is not None and (
            s.code.upper() == spec_filter.upper() or svc.fold(spec_filter) in svc.fold(s.name_fr)
        )
        by_terms = bool(terms) and any(t in text for t in terms)
        if by_filter or by_terms:
            out.append({"id": s.id, "code": s.code, "name": s.name_fr})
    return out


async def search_catalogue(
    session: AsyncSession, params: SearchCatalogueInput, user: CurrentUser | None = None
) -> SearchCatalogueOutput:
    """Recherche déterministe de formations publiées et valides (outil d'agent)."""
    del user  # lecture publique : l'identité n'élargit ni ne restreint rien
    d = params.on_date or svc.today_tunis()
    items, meta = await svc.search_programmes(
        session,
        svc.ProgrammeFilters(
            q=params.query,
            institution=[params.institution] if params.institution else [],
            level=[params.level] if params.level else [],
            speciality=params.speciality,
            on_date=d,
        ),
        PageParams(page=1, page_size=params.limit),
    )
    results = [
        CatalogueHit(
            programme_id=it["id"],
            code=it["code"],
            name=it["name"],
            name_ar=it["name_ar"],
            institution=it["institution"],
            level=it["level"],
            diploma_name=it["diploma_name"],
            duration_years=it["duration_years"],
            matched_specialities=await _matched_specialities(session, it["id"], d, params),
            api_path=f"{API_PREFIX}/catalogue/programmes/{it['id']}",
            source=it["source"],
        )
        for it in items
    ]
    return SearchCatalogueOutput(
        on_date=d,
        total=meta["total_items"],
        results=results,
        truncated=meta["total_items"] > len(results),
    )


# ============ Path Explorer : passerelles depuis X ============


class ExplorePathsInput(BaseModel):
    """Paramètres de `explore_paths_from` : la formation de départ (id OU code)."""

    model_config = ConfigDict(extra="forbid")

    programme_id: uuid.UUID | None = Field(default=None, description="Formation de départ.")
    programme_code: str | None = Field(
        default=None, max_length=32, description="Ou son code officiel (ex. IIT-PREPA)."
    )
    speciality_id: uuid.UUID | None = Field(
        default=None,
        description="Spécialité de départ (passerelles de la spécialité et de toute la formation).",
    )
    on_date: date | None = None


class PathOption(BaseModel):
    """Un parcours possible via une passerelle officielle."""

    bridge_id: uuid.UUID
    to_programme: ProgrammeRef
    to_speciality: SpecialityRef | None
    from_speciality: SpecialityRef | None
    after_years: int = Field(description="Années à valider dans la formation de départ.")
    entry_level: int = Field(description="Année d'entrée dans la formation d'arrivée.")
    access_mode: AccessMode
    conditions: str = Field(description="Résumé officiel des conditions (à citer).")
    total_duration_years: int = Field(
        description="Durée totale calculée par le code : after_years + (durée de la formation "
        "d'arrivée − entry_level + 1)."
    )
    api_path: str
    source: SourceRef


class ExplorePathsOutput(BaseModel):
    on_date: date
    from_programme: ProgrammeRef
    options: list[PathOption]


async def explore_paths_from(
    session: AsyncSession, params: ExplorePathsInput, user: CurrentUser | None = None
) -> ExplorePathsOutput:
    """Passerelles officielles au départ d'une formation, durée totale calculée par le code."""
    del user
    d = params.on_date or svc.today_tunis()
    programme_id = params.programme_id
    if programme_id is None:
        if not params.programme_code:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                message="Indiquez la formation de départ (programme_id ou programme_code).",
                details=[{"field": "programme_id", "issue": "required"}],
            )
        programme_id = await session.scalar(
            select(Programme.id).where(
                func.upper(Programme.code) == params.programme_code.strip().upper()
            )
        )
        if programme_id is None:
            raise AppError(ErrorCode.NOT_FOUND, details={"programme_code": params.programme_code})
    prog, inst = await svc.get_official_programme(session, programme_id, d)
    bridges = await svc.query_bridges(
        session, d, from_programme_id=prog.id, from_speciality_id=params.speciality_id
    )
    options = []
    for b in bridges[0]:
        remaining = max(b["to_duration_years"] - b["entry_level"] + 1, 0)
        options.append(
            PathOption(
                bridge_id=b["id"],
                to_programme=b["to_programme"],
                to_speciality=b["to_speciality"],
                from_speciality=b["from_speciality"],
                after_years=b["after_years"],
                entry_level=b["entry_level"],
                access_mode=b["access_mode"],
                conditions=b["label"],
                total_duration_years=b["after_years"] + remaining,
                api_path=f"{API_PREFIX}/catalogue/programmes/{b['to_programme']['id']}",
                source=b["source"],
            )
        )
    options.sort(key=lambda o: (o.total_duration_years, o.to_programme.name))
    return ExplorePathsOutput(
        on_date=d, from_programme=svc.programme_ref(prog, inst.code), options=options
    )


#: Déclarations prêtes pour E4 : nom → (fonction, modèle d'entrée, modèle de sortie, description).
TOOLS = {
    "search_catalogue": (
        search_catalogue,
        SearchCatalogueInput,
        SearchCatalogueOutput,
        "Chercher des formations officielles (publiées et valides) de l'IIT et de l'ISB par "
        "mots-clés, établissement, niveau ou spécialité.",
    ),
    "explore_paths_from": (
        explore_paths_from,
        ExplorePathsInput,
        ExplorePathsOutput,
        "Lister les passerelles officielles au départ d'une formation (Prépa → Ingénieur, "
        "Licence → Ingénieur…) avec la durée totale du parcours.",
    ),
}

__all__ = [
    "TOOLS",
    "CatalogueHit",
    "ExplorePathsInput",
    "ExplorePathsOutput",
    "PathOption",
    "SearchCatalogueInput",
    "SearchCatalogueOutput",
    "explore_paths_from",
    "search_catalogue",
]
