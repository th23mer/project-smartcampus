"""Service des formations, spécialités, matières et passerelles (SA-20).

Lecture publique : uniquement les lignes **publiées et valides à la date D** (SA-12 §0) ; une
formation n'est visible que si son établissement l'est aussi ; une spécialité, que si sa
formation l'est ; une passerelle, que si ses deux extrémités le sont. Recherche par mots-clés
insensible à la casse et aux accents (repli latin + normalisation de l'arabe), filtres, tri et
pagination SA-5.

Écriture staff : création et modification de brouillons, contrôle de rôle et de périmètre,
ETag / If-Match. Les transitions (submit, publish, reject, archive, new-version) passent par le
noyau `publication.py` (SA-21) avec les `PublishableSpec` déclarées ici.

Aucune règle n'est confiée à un LLM : tout est du code déterministe.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import ColumnElement, and_, case, exists, false, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.errors import AppError, ErrorCode
from app.core.pagination import PageParams
from app.core.security import CurrentUser
from app.models import Bridge, Institution, Programme, Speciality, Subject
from app.services.catalogue import publication as pub
from app.services.catalogue.publication import (
    Action,
    PublishableSpec,
    authorize,
    check_if_match,
    ensure_draft,
    official_filter,
    programme_institution_expr,
    same_key,
    today_tunis,
)
from app.services.catalogue.tx import staff_transaction

#: Niveaux acceptés en filtre (valeurs SA-3, alias SA-5 et français) → `programme_type`.
LEVEL_ALIASES: dict[str, str] = {
    "preparatory": "preparatory",
    "prepa": "preparatory",
    "licence": "licence",
    "license": "licence",
    "engineering": "engineering",
    "ingenieur": "engineering",
    "ingenierie": "engineering",
    "master": "master",
    "mastere": "master",
    "other": "other",
}

PROGRAMME_SORTS = (
    "relevance",
    "name",
    "-name",
    "code",
    "-code",
    "duration_years",
    "-duration_years",
)
BRIDGE_SORTS = ("from", "-from", "to", "-to", "entry_level", "-entry_level")
STAFF_SORTS = ("updated_at", "-updated_at", "created_at", "-created_at", "code", "-code")


# ============ Repli des accents (recherche insensible aux accents) ============

# Même table en Python (requête) et en SQL (`translate`) : aucun écart entre les deux côtés,
# sans extension `unaccent` (absente du socle SA-16). Les caractères de _DELETE sont supprimés
# (diacritiques arabes, tatweel) ; les formes de alef, ya, ta marbuta… sont unifiées.
_MAP_FROM = "àáâãäåÀÁÂÃÄÅçÇèéêëÈÉÊËìíîïÌÍÎÏñÑòóôõöÒÓÔÕÖùúûüÙÚÛÜýÿÝ’أإآٱىةؤئ"
_MAP_TO = "aaaaaaaaaaaacceeeeeeeeiiiiiiiinnoooooooooouuuuuuuuyyy'اااايهوي"
_DELETE = "ًٌٍَُِّْٰـ"
if len(_MAP_FROM) != len(_MAP_TO):  # pragma: no cover - garde de cohérence à l'import
    raise RuntimeError("Table de repli des accents incohérente.")
_PY_TABLE = str.maketrans(_MAP_FROM, _MAP_TO, _DELETE)


def fold(text: str) -> str:
    """Forme de comparaison : sans accents latins, arabe normalisé, minuscules, espaces réduits."""
    return " ".join(text.translate(_PY_TABLE).lower().split())


def folded(column: Any) -> ColumnElement[str]:
    """Équivalent SQL de `fold` (sans réduction des espaces) sur une colonne texte."""
    return func.lower(func.translate(func.coalesce(column, ""), _MAP_FROM + _DELETE, _MAP_TO))


def _like_pattern(token: str) -> str:
    escaped = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _matches(columns: Iterable[Any], token: str) -> ColumnElement[bool]:
    pattern = _like_pattern(token)
    return or_(*(folded(c).like(pattern, escape="\\") for c in columns))


def tokens_of(query: str | None, *, max_tokens: int = 8) -> list[str]:
    """Mots de la requête (repliés), sans doublons, au plus `max_tokens`."""
    if not query:
        return []
    seen: list[str] = []
    for tok in fold(query).split():
        if tok not in seen:
            seen.append(tok)
    return seen[:max_tokens]


# ============ Petits utilitaires ============


def official(model: Any, d: date) -> ColumnElement[bool]:
    """Filtre « publié et valide à la date D » (le seul utilisé par l'agent)."""
    return official_filter(model, d)


def source_of(row: Any, entity_type: str, version: int | None = None) -> dict[str, Any]:
    """Référence de source officielle (`SourceRef`) d'une ligne publiée.

    `version` : rang de publication pour les faits versionnés ; 1 pour une entité stable.
    """
    return {
        "entity_type": entity_type,
        "entity_id": row.id,
        "version": version if version is not None else 1,
        "published_at": row.published_at,
        "valid_from": row.valid_from,
        "valid_to": row.valid_to,
    }


def normalize_levels(levels: Iterable[str] | None) -> list[str]:
    """Alias de niveau → `programme_type` ; 422 VALIDATION_ERROR si inconnu."""
    result: list[str] = []
    for raw in levels or []:
        key = fold(raw)
        if key not in LEVEL_ALIASES:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                details=[
                    {
                        "field": "level",
                        "issue": "unknown_value",
                        "location": "query",
                        "allowed": sorted(set(LEVEL_ALIASES.values())),
                    }
                ],
            )
        if LEVEL_ALIASES[key] not in result:
            result.append(LEVEL_ALIASES[key])
    return result


def _institution_clause(values: Iterable[str] | None, inst: Any) -> ColumnElement[bool] | None:
    """Filtre établissement : code (IIT, ISB ; insensible à la casse) ou UUID, valeurs répétées."""
    conds: list[ColumnElement[bool]] = []
    for raw in values or []:
        raw = raw.strip()
        if not raw:
            continue
        try:
            conds.append(inst.id == uuid.UUID(raw))
        except ValueError:
            conds.append(func.upper(inst.code) == raw.upper())
    return or_(*conds) if conds else None


def check_sort(sort: str | None, allowed: Sequence[str]) -> None:
    if sort is not None and sort not in allowed:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            details=[
                {
                    "field": "sort",
                    "issue": "unknown_value",
                    "location": "query",
                    "allowed": list(allowed),
                }
            ],
        )


def page_meta(total: int, params: PageParams) -> dict[str, int]:
    return {
        "page": params.page,
        "page_size": params.page_size,
        "total_items": total,
        "total_pages": math.ceil(total / params.page_size) if total else 0,
    }


def _not_found_field(field_name: str) -> AppError:
    return AppError(
        ErrorCode.VALIDATION_ERROR,
        details=[{"field": field_name, "issue": "not_found", "location": "body"}],
    )


# ============ Déclarations pour le workflow de publication (SA-21) ============

INSTITUTION_SPEC = PublishableSpec(
    entity_type="institution",
    model=Institution,
    institution_expr=lambda: Institution.id,
    label_fr="établissement",
)
PROGRAMME_SPEC = PublishableSpec(
    entity_type="programme",
    model=Programme,
    institution_expr=lambda: Programme.institution_id,
    label_fr="formation",
)
SPECIALITY_SPEC = PublishableSpec(
    entity_type="speciality",
    model=Speciality,
    institution_expr=lambda: programme_institution_expr(Speciality.programme_id),
    label_fr="spécialité",
)
BRIDGE_SPEC = PublishableSpec(
    entity_type="bridge",
    model=Bridge,
    institution_expr=lambda: programme_institution_expr(Bridge.source_programme_id),
    business_key=lambda r: same_key(
        (Bridge.source_programme_id, r.source_programme_id),
        (Bridge.source_speciality_id, r.source_speciality_id),
        (Bridge.target_programme_id, r.target_programme_id),
        (Bridge.target_speciality_id, r.target_speciality_id),
        (Bridge.target_entry_level, r.target_entry_level),
    ),
    label_fr="passerelle",
)
#: Matière : référentiel interne sans publication ; la spec sert au périmètre seulement.
SUBJECT_SPEC = PublishableSpec(
    entity_type="subject",
    model=Subject,
    institution_expr=lambda: Subject.institution_id,
    label_fr="matière",
)


# ============ Lecture publique : établissements ============


async def list_institutions(session: AsyncSession, d: date) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(Institution).where(official(Institution, d)).order_by(Institution.code)
        )
    ).all()
    return [
        {
            "id": i.id,
            "code": i.code,
            "name": i.name_fr,
            "name_ar": i.name_ar,
            "city": i.city,
            "website_url": i.website_url,
            "description": i.description_fr,
            "source": source_of(i, "institution"),
        }
        for i in rows
    ]


# ============ Lecture publique : formations ============


@dataclass
class ProgrammeFilters:
    """Filtres de `GET /catalogue/programmes` et de l'outil `search_catalogue`."""

    q: str | None = None
    institution: list[str] = field(default_factory=list)
    level: list[str] = field(default_factory=list)
    speciality: str | None = None
    sort: str | None = None
    on_date: date | None = None


def _official_speciality_of(d: date, *conds: ColumnElement[bool]) -> ColumnElement[bool]:
    return exists(
        select(Speciality.id).where(
            Speciality.programme_id == Programme.id, official(Speciality, d), *conds
        )
    )


def _speciality_match(d: date, value: str) -> ColumnElement[bool]:
    """Formation ayant une spécialité officielle de code `value` ou dont le nom le contient."""
    return _official_speciality_of(
        d,
        or_(
            func.upper(Speciality.code) == value.strip().upper(),
            _matches((Speciality.name_fr, Speciality.name_ar), fold(value)),
        ),
    )


_PROGRAMME_TEXT = (
    Programme.code,
    Programme.name_fr,
    Programme.name_ar,
    Programme.diploma_name_fr,
    Programme.description_fr,
    Programme.career_outcomes_fr,
)
_SPECIALITY_TEXT = (
    Speciality.code,
    Speciality.name_fr,
    Speciality.name_ar,
    Speciality.description_fr,
    Speciality.career_outcomes_fr,
)


def _keyword_clause(d: date, tokens: list[str]) -> ColumnElement[bool]:
    """Chaque mot doit apparaître dans un champ de la formation ou d'une de ses spécialités."""
    if not tokens:
        return true()
    return and_(
        *(
            or_(
                _matches(_PROGRAMME_TEXT, tok),
                _official_speciality_of(d, _matches(_SPECIALITY_TEXT, tok)),
            )
            for tok in tokens
        )
    )


def _speciality_count(d: date) -> Any:
    return (
        select(func.count(Speciality.id))
        .where(Speciality.programme_id == Programme.id, official(Speciality, d))
        .correlate(Programme)
        .scalar_subquery()
    )


def _programme_order(sort: str, tokens: list[str]) -> list[Any]:
    name_key = folded(Programme.name_fr)
    desc = sort.startswith("-")
    key = sort.lstrip("-")
    if key == "relevance":
        if not tokens:
            return [name_key, Programme.code]
        # Pertinence simple et explicable : nom qui commence par la requête, puis nom qui la
        # contient, puis le reste (description, débouchés, spécialité…).
        phrase = " ".join(tokens)
        rank = case(
            (name_key.like(_like_pattern(phrase)[1:], escape="\\"), 0),
            (name_key.like(_like_pattern(phrase), escape="\\"), 1),
            else_=2,
        )
        return [rank, name_key, Programme.code]
    if key == "name":
        return [name_key.desc() if desc else name_key, Programme.code]
    if key == "code":
        return [Programme.code.desc() if desc else Programme.code]
    col = Programme.duration_years
    return [col.desc() if desc else col, name_key, Programme.code]


async def search_programmes(
    session: AsyncSession, filters: ProgrammeFilters, params: PageParams
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Formations publiées et valides, filtrées, triées et paginées (SA-5 §1.5)."""
    d = filters.on_date or today_tunis()
    check_sort(filters.sort, PROGRAMME_SORTS)
    levels = normalize_levels(filters.level)
    tokens = tokens_of(filters.q)

    where: list[ColumnElement[bool]] = [official(Programme, d), official(Institution, d)]
    inst_clause = _institution_clause(filters.institution, Institution)
    if inst_clause is not None:
        where.append(inst_clause)
    if levels:
        where.append(Programme.programme_type.in_(levels))
    if filters.speciality and filters.speciality.strip():
        where.append(_speciality_match(d, filters.speciality))
    if tokens:
        where.append(_keyword_clause(d, tokens))

    total = (
        await session.execute(
            select(func.count(Programme.id))
            .join(Institution, Institution.id == Programme.institution_id)
            .where(*where)
        )
    ).scalar_one()
    stmt = (
        select(Programme, Institution.code, _speciality_count(d))
        .join(Institution, Institution.id == Programme.institution_id)
        .where(*where)
        .order_by(*_programme_order(filters.sort or ("relevance" if tokens else "name"), tokens))
        .offset(params.offset)
        .limit(params.limit)
    )
    rows = (await session.execute(stmt)).all()
    return [_programme_summary(p, ic, n) for p, ic, n in rows], page_meta(total, params)


def _programme_summary(p: Programme, inst_code: str, spec_count: int) -> dict[str, Any]:
    return {
        "id": p.id,
        "code": p.code,
        "name": p.name_fr,
        "name_ar": p.name_ar,
        "institution": inst_code,
        "institution_id": p.institution_id,
        "level": p.programme_type,
        "diploma_name": p.diploma_name_fr,
        "duration_years": p.duration_years,
        "total_ects": p.total_ects,
        "speciality_count": spec_count,
        "source": source_of(p, "programme"),
    }


def programme_ref(p: Programme, inst_code: str) -> dict[str, Any]:
    return {
        "id": p.id,
        "code": p.code,
        "name": p.name_fr,
        "institution": inst_code,
        "level": p.programme_type,
    }


async def get_official_programme(
    session: AsyncSession, programme_id: uuid.UUID, d: date
) -> tuple[Programme, Institution]:
    """Formation publiée et valide (et son établissement) ; 404 sinon (brouillon invisible)."""
    row = (
        await session.execute(
            select(Programme, Institution)
            .join(Institution, Institution.id == Programme.institution_id)
            .where(Programme.id == programme_id, official(Programme, d), official(Institution, d))
        )
    ).first()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND)
    return row[0], row[1]


async def get_programme_detail(
    session: AsyncSession, programme_id: uuid.UUID, d: date | None = None
) -> dict[str, Any]:
    """Fiche formation publique : spécialités et passerelles officielles à la date D."""
    d = d or today_tunis()
    prog, inst = await get_official_programme(session, programme_id, d)
    specs = (
        await session.scalars(
            select(Speciality)
            .where(Speciality.programme_id == prog.id, official(Speciality, d))
            .order_by(Speciality.code)
        )
    ).all()
    ref = programme_ref(prog, inst.code)
    from_items, _ = await query_bridges(session, d, from_programme_id=prog.id)
    to_items, _ = await query_bridges(session, d, to_programme_id=prog.id)
    return {
        **_programme_summary(prog, inst.code, len(specs)),
        "institution_name": inst.name_fr,
        "description": prog.description_fr,
        "career_outcomes": prog.career_outcomes_fr,
        "specialities": [_speciality_public(s, ref) for s in specs],
        "bridges_from": from_items,
        "bridges_to": to_items,
    }


def _speciality_public(s: Speciality, prog_ref: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": s.id,
        "code": s.code,
        "name": s.name_fr,
        "name_ar": s.name_ar,
        "description": s.description_fr,
        "career_outcomes": s.career_outcomes_fr,
        "programme": prog_ref,
        "source": source_of(s, "speciality"),
    }


# ============ Lecture publique : spécialités ============


async def list_specialities(
    session: AsyncSession,
    params: PageParams,
    *,
    programme_id: uuid.UUID | None = None,
    institution: list[str] | None = None,
    q: str | None = None,
    on_date: date | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    d = on_date or today_tunis()
    where: list[ColumnElement[bool]] = [
        official(Speciality, d),
        official(Programme, d),
        official(Institution, d),
    ]
    if programme_id:
        where.append(Speciality.programme_id == programme_id)
    inst_clause = _institution_clause(institution, Institution)
    if inst_clause is not None:
        where.append(inst_clause)
    where.extend(_matches((*_SPECIALITY_TEXT, Programme.name_fr), tok) for tok in tokens_of(q))
    base = (
        select(Speciality, Programme, Institution.code)
        .join(Programme, Programme.id == Speciality.programme_id)
        .join(Institution, Institution.id == Programme.institution_id)
        .where(*where)
    )
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        await session.execute(
            base.order_by(folded(Programme.name_fr), Speciality.code)
            .offset(params.offset)
            .limit(params.limit)
        )
    ).all()
    items = [_speciality_public(s, programme_ref(p, ic)) for s, p, ic in rows]
    return items, page_meta(total, params)


async def get_speciality(
    session: AsyncSession, speciality_id: uuid.UUID, d: date | None = None
) -> dict[str, Any]:
    d = d or today_tunis()
    row = (
        await session.execute(
            select(Speciality, Programme, Institution.code)
            .join(Programme, Programme.id == Speciality.programme_id)
            .join(Institution, Institution.id == Programme.institution_id)
            .where(
                Speciality.id == speciality_id,
                official(Speciality, d),
                official(Programme, d),
                official(Institution, d),
            )
        )
    ).first()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND)
    s, p, ic = row
    return _speciality_public(s, programme_ref(p, ic))


# ============ Lecture publique : passerelles ============


def _spec_ref(s: Speciality | None) -> dict[str, Any] | None:
    return None if s is None else {"id": s.id, "code": s.code, "name": s.name_fr}


async def query_bridges(
    session: AsyncSession,
    d: date,
    *,
    from_programme_id: uuid.UUID | None = None,
    to_programme_id: uuid.UUID | None = None,
    from_speciality_id: uuid.UUID | None = None,
    institution: list[str] | None = None,
    to_level: list[str] | None = None,
    sort: str | None = None,
    params: PageParams | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Passerelles officielles dont les deux extrémités (et spécialités citées) le sont aussi.

    Chaque élément porte en plus `to_duration_years` (durée du parcours d'arrivée), utilisé
    par l'explorateur de parcours et ignoré par le schéma public.
    """
    check_sort(sort, BRIDGE_SORTS)
    levels = normalize_levels(to_level)
    sp, tp = aliased(Programme), aliased(Programme)
    si, ti = aliased(Institution), aliased(Institution)
    ss, ts = aliased(Speciality), aliased(Speciality)
    where: list[ColumnElement[bool]] = [
        official(Bridge, d),
        official(sp, d),
        official(tp, d),
        official(si, d),
        official(ti, d),
        # Une spécialité citée doit elle-même être officielle, sinon la passerelle est masquée.
        or_(Bridge.source_speciality_id.is_(None), official(ss, d)),
        or_(Bridge.target_speciality_id.is_(None), official(ts, d)),
    ]
    if from_programme_id:
        where.append(Bridge.source_programme_id == from_programme_id)
    if to_programme_id:
        where.append(Bridge.target_programme_id == to_programme_id)
    if from_speciality_id:
        # Passerelles de cette spécialité ET celles ouvertes à toute la formation.
        where.append(
            or_(
                Bridge.source_speciality_id.is_(None),
                Bridge.source_speciality_id == from_speciality_id,
            )
        )
    src_inst = _institution_clause(institution, si)
    if src_inst is not None:
        where.append(or_(src_inst, _institution_clause(institution, ti) or false()))
    if levels:
        where.append(tp.programme_type.in_(levels))

    base = (
        select(Bridge, sp, si.code, ss, tp, ti.code, ts)
        .join(sp, sp.id == Bridge.source_programme_id)
        .join(si, si.id == sp.institution_id)
        .join(tp, tp.id == Bridge.target_programme_id)
        .join(ti, ti.id == tp.institution_id)
        .outerjoin(ss, ss.id == Bridge.source_speciality_id)
        .outerjoin(ts, ts.id == Bridge.target_speciality_id)
        .where(*where)
    )
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    key = (sort or "from").lstrip("-")
    col = {
        "from": folded(sp.name_fr),
        "to": folded(tp.name_fr),
        "entry_level": Bridge.target_entry_level,
    }[key]
    stmt = base.order_by(
        col.desc() if sort and sort.startswith("-") else col,
        Bridge.source_min_completed_years,
        folded(tp.name_fr),
        Bridge.id,
    )
    if params is not None:
        stmt = stmt.offset(params.offset).limit(params.limit)
    rows = (await session.execute(stmt)).all()
    items = []
    for b, src, src_ic, src_spec, tgt, tgt_ic, tgt_spec in rows:
        version = await pub.version_number(session, BRIDGE_SPEC, b)
        items.append(
            {
                "id": b.id,
                "from_programme": programme_ref(src, src_ic),
                "from_speciality": _spec_ref(src_spec),
                "after_years": b.source_min_completed_years,
                "to_programme": programme_ref(tgt, tgt_ic),
                "to_speciality": _spec_ref(tgt_spec),
                "entry_level": b.target_entry_level,
                "access_mode": b.access_mode,
                "label": b.conditions_summary_fr,
                "source": source_of(b, "bridge", version),
                "to_duration_years": tgt.duration_years,
            }
        )
    return items, total


async def list_bridges(
    session: AsyncSession,
    params: PageParams,
    *,
    from_programme_id: uuid.UUID | None = None,
    to_programme_id: uuid.UUID | None = None,
    institution: list[str] | None = None,
    to_level: list[str] | None = None,
    sort: str | None = None,
    on_date: date | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    items, total = await query_bridges(
        session,
        on_date or today_tunis(),
        from_programme_id=from_programme_id,
        to_programme_id=to_programme_id,
        institution=institution,
        to_level=to_level,
        sort=sort,
        params=params,
    )
    return items, page_meta(total, params)


# ============ Staff : lecture (tous statuts, périmètre) ============


async def staff_list(
    session: AsyncSession,
    user: CurrentUser,
    spec: PublishableSpec,
    params: PageParams,
    *,
    statuses: list[str] | None = None,
    institution: list[str] | None = None,
    programme_id: uuid.UUID | None = None,
    q: str | None = None,
    sort: str | None = None,
) -> tuple[list[Any], dict[str, int]]:
    """Liste staff d'une entité, limitée au périmètre (règle S) ; direction et admin : tout."""
    model = spec.model
    check_sort(sort, STAFF_SORTS)
    where: list[ColumnElement[bool]] = []
    scope_clause = pub.scope_filter(spec, await pub.staff_scope(session, user))
    if scope_clause is not None:
        where.append(scope_clause)
    if statuses and hasattr(model, "publication_status"):
        where.append(model.publication_status.in_(statuses))
    inst_clause = _institution_clause(institution, Institution)
    if inst_clause is not None:
        where.append(spec.institution_expr().in_(select(Institution.id).where(inst_clause)))
    if programme_id is not None:
        for name in ("programme_id", "source_programme_id"):
            if hasattr(model, name):
                where.append(getattr(model, name) == programme_id)
                break
    text_cols = [
        getattr(model, c)
        for c in ("code", "name_fr", "name_ar", "version_label", "conditions_summary_fr")
        if hasattr(model, c)
    ]
    where.extend(_matches(text_cols, tok) for tok in tokens_of(q))
    stmt = select(model).where(*where)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    sort = sort or "-updated_at"
    col = getattr(model, sort.lstrip("-"), None)
    if col is None:  # `code` n'existe pas sur curriculum / bridge
        col = model.updated_at
    order = col.desc() if sort.startswith("-") else col
    rows = (
        await session.scalars(
            stmt.order_by(order, model.id).offset(params.offset).limit(params.limit)
        )
    ).all()
    return list(rows), page_meta(total, params)


async def staff_get(
    session: AsyncSession, user: CurrentUser, spec: PublishableSpec, row_id: uuid.UUID
) -> Any:
    """Lecture staff d'une ligne (tous statuts) ; hors périmètre → 404."""
    return await pub.get_for_staff(session, spec, row_id, user)


# ============ Staff : création et modification de brouillons ============


async def load_for_edit(
    session: AsyncSession,
    user: CurrentUser,
    spec: PublishableSpec,
    row_id: uuid.UUID,
    if_match: str | None,
) -> Any:
    """Ligne verrouillée, rôle et périmètre d'auteur vérifiés, If-Match obligatoire."""
    row = await pub.load_for_update(session, spec, row_id)
    await authorize(session, user, Action.EDIT, await pub.institution_of(session, spec, row))
    check_if_match(row, if_match, required=True)
    return row


async def authorize_create(
    session: AsyncSession, user: CurrentUser, institution_id: uuid.UUID | None
) -> None:
    await authorize(session, user, Action.CREATE, institution_id, existing=False)


def check_validity(values: dict[str, Any]) -> None:
    start, end = values.get("valid_from"), values.get("valid_to")
    if start is not None and end is not None and end <= start:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            details=[
                {"field": "valid_to", "issue": "must_be_after_valid_from", "location": "body"}
            ],
        )


def apply_patch(row: Any, data: Any, *, non_nullable: Iterable[str] = ()) -> None:
    """Applique les champs envoyés (PATCH partiel) ; null interdit sur les colonnes requises."""
    changes = data.model_dump(exclude_unset=True)
    required = set(non_nullable)
    nulls = [k for k, v in changes.items() if v is None and k in required]
    if nulls:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            details=[{"field": k, "issue": "null_not_allowed", "location": "body"} for k in nulls],
        )
    if hasattr(row, "valid_from"):
        check_validity(
            {
                "valid_from": changes.get("valid_from", row.valid_from),
                "valid_to": changes.get("valid_to", row.valid_to),
            }
        )
    for key, value in changes.items():
        setattr(row, key, value)


async def check_speciality_of(
    session: AsyncSession,
    speciality_id: uuid.UUID | None,
    programme_id: uuid.UUID,
    field_name: str,
) -> None:
    """Cohérence spécialité/formation vérifiée avant la FK composite (message clair)."""
    if speciality_id is None:
        return
    owner = await session.scalar(
        select(Speciality.programme_id).where(Speciality.id == speciality_id)
    )
    if owner != programme_id:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            message="La spécialité n'appartient pas à la formation indiquée.",
            details=[{"field": field_name, "issue": "not_in_programme", "location": "body"}],
        )


async def programme_for_create(
    session: AsyncSession, user: CurrentUser, programme_id: uuid.UUID, field_name: str
) -> uuid.UUID:
    """Formation référencée par un nouveau brouillon : doit exister et être dans le périmètre."""
    inst_id = await pub.programme_institution_id(session, programme_id)
    if inst_id is None:
        raise _not_found_field(field_name)
    await authorize_create(session, user, inst_id)
    return inst_id


async def finish(session: AsyncSession, row: Any) -> Any:
    """Recharge la ligne après commit (id, horodatages, colonnes générées)."""
    await session.refresh(row)
    return row


async def create_programme(session: AsyncSession, user: CurrentUser, data: Any) -> Programme:
    async with staff_transaction(session, user):
        if await session.get(Institution, data.institution_id) is None:
            raise _not_found_field("institution_id")
        await authorize_create(session, user, data.institution_id)
        row = Programme(**data.model_dump(), created_by=user.id)
        session.add(row)
    return await finish(session, row)


async def update_programme(
    session: AsyncSession, user: CurrentUser, row_id: uuid.UUID, data: Any, if_match: str | None
) -> Programme:
    async with staff_transaction(session, user):
        row = await load_for_edit(session, user, PROGRAMME_SPEC, row_id, if_match)
        ensure_draft(row)
        apply_patch(row, data, non_nullable=("code", "name_fr", "programme_type", "duration_years"))
    return await finish(session, row)


async def create_speciality(session: AsyncSession, user: CurrentUser, data: Any) -> Speciality:
    async with staff_transaction(session, user):
        await programme_for_create(session, user, data.programme_id, "programme_id")
        row = Speciality(**data.model_dump(), created_by=user.id)
        session.add(row)
    return await finish(session, row)


async def update_speciality(
    session: AsyncSession, user: CurrentUser, row_id: uuid.UUID, data: Any, if_match: str | None
) -> Speciality:
    async with staff_transaction(session, user):
        row = await load_for_edit(session, user, SPECIALITY_SPEC, row_id, if_match)
        ensure_draft(row)
        apply_patch(row, data, non_nullable=("code", "name_fr"))
    return await finish(session, row)


async def create_subject(session: AsyncSession, user: CurrentUser, data: Any) -> Subject:
    async with staff_transaction(session, user):
        if await session.get(Institution, data.institution_id) is None:
            raise _not_found_field("institution_id")
        await authorize_create(session, user, data.institution_id)
        row = Subject(**data.model_dump())
        session.add(row)
    return await finish(session, row)


async def update_subject(
    session: AsyncSession, user: CurrentUser, row_id: uuid.UUID, data: Any, if_match: str | None
) -> Subject:
    """Référentiel interne : modifiable sur place (tracé par l'audit), sans publication."""
    async with staff_transaction(session, user):
        row = await load_for_edit(session, user, SUBJECT_SPEC, row_id, if_match)
        apply_patch(row, data, non_nullable=("code", "name_fr"))
    return await finish(session, row)


async def create_bridge(session: AsyncSession, user: CurrentUser, data: Any) -> Bridge:
    async with staff_transaction(session, user):
        await programme_for_create(session, user, data.source_programme_id, "source_programme_id")
        if await pub.programme_institution_id(session, data.target_programme_id) is None:
            raise _not_found_field("target_programme_id")
        await check_speciality_of(
            session, data.source_speciality_id, data.source_programme_id, "source_speciality_id"
        )
        await check_speciality_of(
            session, data.target_speciality_id, data.target_programme_id, "target_speciality_id"
        )
        row = Bridge(**data.model_dump(), created_by=user.id)
        session.add(row)
    return await finish(session, row)


async def update_bridge(
    session: AsyncSession, user: CurrentUser, row_id: uuid.UUID, data: Any, if_match: str | None
) -> Bridge:
    async with staff_transaction(session, user):
        row = await load_for_edit(session, user, BRIDGE_SPEC, row_id, if_match)
        ensure_draft(row)
        apply_patch(
            row,
            data,
            non_nullable=(
                "source_min_completed_years",
                "target_entry_level",
                "access_mode",
                "conditions_summary_fr",
            ),
        )
    return await finish(session, row)


__all__ = [
    "BRIDGE_SPEC",
    "INSTITUTION_SPEC",
    "LEVEL_ALIASES",
    "PROGRAMME_SPEC",
    "SPECIALITY_SPEC",
    "SUBJECT_SPEC",
    "ProgrammeFilters",
    "check_speciality_of",
    "create_bridge",
    "create_programme",
    "create_speciality",
    "create_subject",
    "fold",
    "folded",
    "get_official_programme",
    "get_programme_detail",
    "get_speciality",
    "list_bridges",
    "list_institutions",
    "list_specialities",
    "official",
    "programme_ref",
    "query_bridges",
    "search_programmes",
    "source_of",
    "staff_get",
    "staff_list",
    "today_tunis",
    "update_bridge",
    "update_programme",
    "update_speciality",
    "update_subject",
]
