"""Données de démonstration SmartCampus AI (SA-18) : catalogue IIT/ISB, comptes staff, candidats.

Tout est **synthétique** (aucune donnée réelle, aucun vrai nom, e-mails en @example.tn).

Lancement (depuis `backend/`) :
    uv run python scripts/seed.py                      # base de dev (DATABASE_URL du .env)
    uv run python scripts/seed.py --database-url URL   # autre base (ex. db-test)
    uv run python scripts/seed.py --reset              # base vidée puis recréée, puis seed
Depuis la racine : `make migrate` puis `make seed` (dans le conteneur backend).

Idempotence : chaque objet est cherché par sa clé métier (`code`, e-mail, (formation,
spécialité, année…) pour les faits versionnés) et créé seulement s'il manque. Une ligne qui
existe déjà n'est jamais modifiée : relancer le script ne crée aucun doublon.

Pourquoi `--reset` passe par Alembic : une ligne publiée ou archivée est figée en base
(trigger `guard_published_version`, SA-17) et ne peut pas être supprimée. Pour repartir de zéro,
`--reset` exécute `alembic downgrade base && alembic upgrade head` avec le rôle propriétaire
(MIGRATION_DATABASE_URL), ce qui EFFACE TOUTE LA BASE visée, puis recharge le seed.
Changer une donnée déjà chargée dans `seed_data/` exige donc `--reset`.

Publication à quatre yeux (D-B, D-H) : chaque objet publiable est créé en brouillon par son
rédacteur, soumis (draft → pending_review) puis publié par un AUTRE compte
(published_by ≠ submitted_by), avec `app.current_user_id` posé à chaque étape pour que le
journal d'audit du catalogue enregistre le bon auteur. Chaque transition est aussi tracée dans
`status_history`.

Connexion : rôle applicatif (`smartcampus_app`, DML seulement) en synchrone (psycopg 3) ; une URL
`postgresql+asyncpg://` est convertie automatiquement.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import uuid
from collections import Counter
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPTS_DIR.parent
for _path in (BACKEND_DIR, SCRIPTS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from seed_data import accounts, candidates, catalogue, embedding  # noqa: E402
from sqlalchemy import create_engine, func, select, text  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.db import Base  # noqa: E402
from app.models import (  # noqa: E402
    AcademicRecord,
    AcademicRecordSubject,
    AdmissionCondition,
    AdmissionSubjectRequirement,
    Bridge,
    CandidateProfile,
    Consent,
    Curriculum,
    CurriculumSubject,
    EmbeddingModel,
    FeeSchedule,
    Institution,
    PaymentInstallment,
    PaymentPlan,
    Prerequisite,
    Programme,
    Role,
    Speciality,
    StatusHistory,
    Subject,
    UserAccount,
    UserRole,
)

#: Statuts finaux acceptés dans seed_data (`expired` = publié avec valid_to passé).
TARGET_STATUSES = ("draft", "pending_review", "published", "expired", "archived")
POLICY_VERSION = "2026-11-demo"


# ------------------------------------------------------------------------------------------------
# Outils
# ------------------------------------------------------------------------------------------------
def to_sync_url(url: str) -> str:
    """URL SQLAlchemy du pilote synchrone psycopg 3 (accepte asyncpg, psycopg ou libpq)."""
    scheme, sep, rest = url.partition("://")
    if not sep or not scheme.startswith("postgresql"):
        raise ValueError("URL PostgreSQL attendue (postgresql://, postgresql+asyncpg://…).")
    return f"postgresql+psycopg://{rest}"


def d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def dec(value: str | float | int | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.001"), ROUND_HALF_UP)


class Seeder:
    """Création idempotente des objets, publication à quatre yeux, compteurs."""

    def __init__(self, session: Session) -> None:
        self.s = session
        self.created: Counter[str] = Counter()
        self.existing: Counter[str] = Counter()
        self.staff: dict[str, uuid.UUID] = {}
        self.institutions: dict[str, uuid.UUID] = {}
        self.programmes: dict[str, Programme] = {}
        self.specialities: dict[tuple[str, str], Speciality] = {}
        self.subjects: dict[tuple[str, str], Subject] = {}
        self.programme_institution: dict[str, str] = {}
        self.roles: dict[str, uuid.UUID] = {}

    # --- primitives ---------------------------------------------------------------------------
    def actor(self, user_id: uuid.UUID | None) -> None:
        """`SET LOCAL app.current_user_id` : auteur lu par le trigger d'audit du catalogue."""
        self.s.execute(
            text("SELECT set_config('app.current_user_id', :u, true)"),
            {"u": str(user_id) if user_id else ""},
        )

    def get_or_create(self, model: type, lookup: dict[str, Any], values: dict[str, Any]):
        """Cherche par la clé métier `lookup` (NULL comparé avec IS NULL) ; crée si absent."""
        stmt = select(model)
        for key, value in lookup.items():
            col = getattr(model, key)
            stmt = stmt.where(col.is_(None) if value is None else col == value)
        obj = self.s.scalars(stmt).one_or_none()
        table = model.__tablename__
        if obj is not None:
            self.existing[table] += 1
            return obj, False
        obj = model(**lookup, **values)
        self.s.add(obj)
        self.s.flush()
        self.created[table] += 1
        return obj, True

    def history(
        self,
        entity_type: str,
        entity_id: uuid.UUID,
        from_status: str | None,
        to_status: str,
        user_id: uuid.UUID,
        *,
        requires_human: bool = False,
        reason: str | None = None,
    ) -> None:
        self.s.add(
            StatusHistory(
                entity_type=entity_type,
                entity_id=entity_id,
                from_status=from_status,
                to_status=to_status,
                actor_type="staff",
                actor_user_id=user_id,
                requires_human=requires_human,
                reason=reason,
                metadata_={"source": "seed_sa18"},
            )
        )
        self.created["status_history"] += 1

    def publishable(
        self,
        model: type,
        entity_type: str | None,
        lookup: dict[str, Any],
        values: dict[str, Any],
        *,
        status: str,
        institution: str,
        author: str | None = None,
        publisher: str | None = None,
    ):
        """Crée un objet publiable en suivant le vrai cycle draft → pending_review → published.

        `author` rédige et soumet, `publisher` (un AUTRE compte, D-H) publie ou archive.
        """
        if status not in TARGET_STATUSES:
            raise ValueError(f"Statut de seed inconnu : {status}")
        default_author, default_publisher = accounts.PUBLICATION_PAIRS[institution]
        author_id = self.staff[author or default_author]
        publisher_id = self.staff[publisher or default_publisher]
        assert author_id != publisher_id, "quatre yeux : le publieur doit être un autre compte"

        self.actor(author_id)
        obj, created = self.get_or_create(
            model, lookup, {**values, "publication_status": "draft", "created_by": author_id}
        )
        if not created or status == "draft":
            return obj

        def step(new_status: str, who: uuid.UUID, human: bool, **cols: Any) -> None:
            old = obj.publication_status
            self.actor(who)
            obj.publication_status = new_status
            for key, value in cols.items():
                setattr(obj, key, value)
            self.s.flush()
            if entity_type:
                self.history(entity_type, obj.id, old, new_status, who, requires_human=human)

        step(
            "pending_review",
            author_id,
            False,
            submitted_by=author_id,
            submitted_at=func.clock_timestamp(),
        )
        if status in ("published", "expired", "archived"):
            step(
                "published",
                publisher_id,
                True,
                published_by=publisher_id,
                published_at=func.clock_timestamp(),
            )
        if status == "archived":
            step("archived", publisher_id, True)
        return obj

    # --- étapes du seed -----------------------------------------------------------------------
    def seed_accounts(self) -> None:
        for alias, spec in accounts.STAFF.items():
            user, _ = self.get_or_create(
                UserAccount,
                {"email": spec["email"]},
                {
                    "id": spec["id"],
                    "password_hash": accounts.NO_LOGIN_HASH,
                    "full_name": spec["full_name"],
                    "account_type": "staff",
                    "preferred_language": "fr",
                    "account_status": "active",
                    "email_verified_at": func.now(),
                },
            )
            self.staff[alias] = user.id

    def seed_roles(self) -> None:
        """Rôles (après les institutions : périmètre IIT/ISB, SA-13 D20) et rôles du staff."""
        for spec in accounts.ROLES:
            inst = spec["institution"]
            role, _ = self.get_or_create(
                Role,
                {"code": spec["code"]},
                {
                    "label": spec["label"],
                    "is_staff": spec["is_staff"],
                    "institution_id": self.institutions[inst] if inst else None,
                },
            )
            self.roles[spec["code"]] = role.id
        for alias, spec in accounts.STAFF.items():
            for code in spec["roles"]:
                self.get_or_create(
                    UserRole, {"user_id": self.staff[alias], "role_id": self.roles[code]}, {}
                )

    def seed_institutions(self) -> None:
        for spec in catalogue.INSTITUTIONS:
            author, _ = accounts.PUBLICATION_PAIRS[spec["code"]]
            inst = self.publishable(
                Institution,
                "institution",
                {"code": spec["code"]},
                {
                    "id": spec["id"],
                    "name_fr": spec["name_fr"],
                    "name_ar": spec["name_ar"],
                    "city": spec["city"],
                    "website_url": spec["website_url"],
                    "description_fr": spec["description_fr"],
                    "valid_from": d(spec["valid_from"]),
                },
                status=spec["status"],
                institution=spec["code"],
                author=author,
                publisher="direction",
            )
            self.institutions[spec["code"]] = inst.id

    def seed_programmes(self) -> None:
        for spec in catalogue.PROGRAMMES:
            inst = spec["institution"]
            prog = self.publishable(
                Programme,
                "programme",
                {"code": spec["code"]},
                {
                    "institution_id": self.institutions[inst],
                    "name_fr": spec["name_fr"],
                    "name_ar": spec["name_ar"],
                    "programme_type": spec["programme_type"],
                    "diploma_name_fr": spec["diploma_name_fr"],
                    "duration_years": spec["duration_years"],
                    "total_ects": spec["total_ects"],
                    "description_fr": spec["description_fr"],
                    "career_outcomes_fr": spec["career_outcomes_fr"],
                    "valid_from": d(spec["valid_from"]),
                },
                status=spec["status"],
                institution=inst,
            )
            self.programmes[spec["code"]] = prog
            self.programme_institution[spec["code"]] = inst
        for spec in catalogue.SPECIALITIES:
            prog = self.programmes[spec["programme"]]
            sp = self.publishable(
                Speciality,
                "speciality",
                {"programme_id": prog.id, "code": spec["code"]},
                {
                    "name_fr": spec["name_fr"],
                    "name_ar": spec["name_ar"],
                    "description_fr": spec["description_fr"],
                    "career_outcomes_fr": spec["career_outcomes_fr"],
                    "valid_from": d(spec["valid_from"]),
                },
                status=spec["status"],
                institution=self.programme_institution[spec["programme"]],
            )
            self.specialities[(spec["programme"], spec["code"])] = sp

    def seed_subjects(self) -> None:
        for inst, rows in catalogue.SUBJECTS.items():
            # Le référentiel des matières n'est pas publiable : auteur = rédacteur de l'institution.
            self.actor(self.staff[accounts.PUBLICATION_PAIRS[inst][0]])
            for code, name, domain, _kind, description in rows:
                subject, _ = self.get_or_create(
                    Subject,
                    {"institution_id": self.institutions[inst], "code": code},
                    {
                        "name_fr": name,
                        "domain": domain,
                        "description_fr": description,
                        "learning_outcomes_fr": "Connaître et mettre en œuvre : "
                        f"{description[0].lower()}{description[1:]}",
                    },
                )
                self.subjects[(inst, code)] = subject

    def _spec_id(self, programme: str, speciality: str | None) -> uuid.UUID | None:
        return self.specialities[(programme, speciality)].id if speciality else None

    def seed_curricula(self) -> None:
        kinds = {
            (inst, row[0]): row[3] for inst, rows in catalogue.SUBJECTS.items() for row in rows
        }
        for spec in catalogue.CURRICULA:
            prog_code = spec["programme"]
            inst = self.programme_institution[prog_code]
            prog = self.programmes[prog_code]
            spec_id = self._spec_id(prog_code, spec["speciality"])
            cur = self.publishable(
                Curriculum,
                "curriculum",
                {
                    "programme_id": prog.id,
                    "speciality_id": spec_id,
                    "version_label": spec["version_label"],
                },
                {
                    "academic_year": spec["academic_year"],
                    "total_ects": spec["total_ects"],
                    "notes_fr": spec["notes_fr"],
                    "valid_from": d(spec["valid_from"]),
                    "valid_to": d(spec["valid_to"]),
                },
                status=spec["status"],
                institution=inst,
            )
            # Enfants (catégorie C) : insérables sous une version publiée (SA-17 D1).
            self.actor(self.staff[accounts.PUBLICATION_PAIRS[inst][0]])
            lines: dict[str, CurriculumSubject] = {}
            for code, sem, ue_code, ue_name, coef, ects, elective in spec["subjects"]:
                cm, td, tp = catalogue.hours_for(kinds[(inst, code)], ects)
                line, _ = self.get_or_create(
                    CurriculumSubject,
                    {"curriculum_id": cur.id, "subject_id": self.subjects[(inst, code)].id},
                    {
                        "semester": sem,
                        "teaching_unit_code": ue_code,
                        "teaching_unit_name_fr": ue_name,
                        "coefficient": dec(coef),
                        "ects_credits": dec(ects),
                        "hours_lecture": dec(cm),
                        "hours_tutorial": dec(td),
                        "hours_practical": dec(tp),
                        "is_elective": elective,
                    },
                )
                lines[code] = line
            for target, required, knowledge in spec["prerequisites"]:
                self.get_or_create(
                    Prerequisite,
                    {
                        "curriculum_id": cur.id,
                        "curriculum_subject_id": lines[target].id,
                        "required_subject_id": self.subjects[(inst, required)].id
                        if required
                        else None,
                        "required_knowledge_fr": knowledge,
                    },
                    {"is_mandatory": True},
                )

    def seed_admission(self) -> None:
        for spec in catalogue.ADMISSION_CONDITIONS:
            prog_code = spec["programme"]
            inst = self.programme_institution[prog_code]
            cond = self.publishable(
                AdmissionCondition,
                "admission_condition",
                {
                    "programme_id": self.programmes[prog_code].id,
                    "speciality_id": self._spec_id(prog_code, spec["speciality"]),
                    "entry_level": spec["entry_level"],
                    "applicant_category": spec["applicant_category"],
                    "academic_year": spec["academic_year"],
                    "valid_from": d(spec["valid_from"]),
                },
                {
                    "required_diploma": spec["required_diploma"],
                    "accepted_bac_sections": spec["accepted_bac_sections"],
                    "min_validated_years": spec["min_validated_years"],
                    "min_average": dec(spec["min_average"]),
                    "average_basis": spec["average_basis"],
                    "requires_application_file": spec["requires_application_file"],
                    "requires_test": spec["requires_test"],
                    "requires_interview": spec["requires_interview"],
                    "max_places": spec["max_places"],
                    "summary_fr": spec["summary_fr"],
                    "valid_to": d(spec["valid_to"]),
                },
                status=spec["status"],
                institution=inst,
            )
            self.actor(self.staff[accounts.PUBLICATION_PAIRS[inst][0]])
            for key, name, minimum in spec["requirements"]:
                self.get_or_create(
                    AdmissionSubjectRequirement,
                    {"admission_condition_id": cond.id, "subject_key": key},
                    {"subject_name_fr": name, "min_grade": dec(minimum)},
                )

    def seed_fees(self) -> None:
        for spec in catalogue.FEE_SCHEDULES:
            prog_code = spec["programme"]
            inst = self.programme_institution[prog_code]
            fee = self.publishable(
                FeeSchedule,
                "fee_schedule",
                {
                    "programme_id": self.programmes[prog_code].id,
                    "speciality_id": self._spec_id(prog_code, spec["speciality"]),
                    "study_year": spec["study_year"],
                    "student_category": spec["student_category"],
                    "academic_year": spec["academic_year"],
                    "valid_from": d(spec["valid_from"]),
                },
                {
                    "currency": "TND",
                    "registration_fee": dec(spec["registration_fee"]),
                    "annual_tuition_fee": dec(spec["annual_tuition_fee"]),
                    "other_fees": dec(spec["other_fees"]),
                    "other_fees_label_fr": spec["other_fees_label_fr"],
                    "notes_fr": spec["notes_fr"],
                    "valid_to": d(spec["valid_to"]),
                },
                status=spec["status"],
                institution=inst,
            )
            self.actor(self.staff[accounts.PUBLICATION_PAIRS[inst][0]])
            total = sum(
                Decimal(spec[k]) for k in ("registration_fee", "annual_tuition_fee", "other_fees")
            )
            start = int(spec["academic_year"][:4])
            for code, label, count, discount, default in catalogue.PAYMENT_PLANS:
                plan, _ = self.get_or_create(
                    PaymentPlan,
                    {"fee_schedule_id": fee.id, "code": code},
                    {
                        "label_fr": label,
                        "installment_count": count,
                        "discount_rate": dec(discount),
                        "is_default": default,
                    },
                )
                for no, due_date, due_label, amount in installments(total, count, discount, start):
                    self.get_or_create(
                        PaymentInstallment,
                        {"payment_plan_id": plan.id, "installment_no": no},
                        {"due_date": due_date, "due_label_fr": due_label, "amount": amount},
                    )

    def seed_bridges(self) -> None:
        for spec in catalogue.BRIDGES:
            (src, src_spec), (tgt, tgt_spec) = spec["source"], spec["target"]
            self.publishable(
                Bridge,
                "bridge",
                {
                    "source_programme_id": self.programmes[src].id,
                    "source_speciality_id": self._spec_id(src, src_spec),
                    "target_programme_id": self.programmes[tgt].id,
                    "target_speciality_id": self._spec_id(tgt, tgt_spec),
                    "target_entry_level": spec["level"],
                    "valid_from": d(spec["valid_from"]),
                },
                {
                    "source_min_completed_years": spec["years"],
                    "access_mode": spec["access_mode"],
                    "conditions_summary_fr": spec["summary"],
                    "valid_to": d(spec.get("valid_to")),
                },
                status=spec["status"],
                institution=self.programme_institution[tgt],
            )

    def seed_candidates(self) -> None:
        self.actor(None)
        for spec in candidates.CANDIDATES:
            user, _ = self.get_or_create(
                UserAccount,
                {"email": spec["email"]},
                {
                    "id": spec["id"],
                    "password_hash": accounts.NO_LOGIN_HASH,
                    "full_name": spec["full_name"],
                    "account_type": "candidate",
                    "preferred_language": spec["preferred_language"],
                    "account_status": "active",
                    "email_verified_at": func.now(),
                },
            )
            self.get_or_create(
                UserRole, {"user_id": user.id, "role_id": self.roles["candidate"]}, {}
            )
            for consent_type in ("terms_accepted", "data_processing"):
                self.get_or_create(
                    Consent,
                    {"user_id": user.id, "consent_type": consent_type},
                    {"granted": True, "policy_version": POLICY_VERSION, "channel": "web_form"},
                )
            p = spec["profile"]
            profile, _ = self.get_or_create(
                CandidateProfile,
                {"user_id": user.id},
                {
                    "candidate_type": p["candidate_type"],
                    "birth_date": d(p["birth_date"]),
                    "city": p["city"],
                    "interests": p["interests"],
                    "goals": p["goals"],
                    "constraints": p["constraints"],
                    "profile_status": p["profile_status"],
                    "field_sources": p["field_sources"],
                    "confirmed_at": func.now() if p["profile_status"] == "confirmed" else None,
                },
            )
            for rec in spec["records"]:
                record, _ = self.get_or_create(
                    AcademicRecord,
                    {
                        "candidate_profile_id": profile.id,
                        "record_type": rec["record_type"],
                        "year": rec["year"],
                    },
                    {
                        "bac_section": rec["bac_section"],
                        "institution_name": rec["institution_name"],
                        "diploma_label": rec["diploma_label"],
                        "overall_average": dec(rec["overall_average"]),
                        "orientation_score": dec(rec["orientation_score"]),
                        "source": "declared",
                    },
                )
                for row in rec["subjects"]:
                    label, key, grade, coef, *extra = row
                    credits, hours = [*extra, None, None][:2]
                    self.get_or_create(
                        AcademicRecordSubject,
                        {"academic_record_id": record.id, "subject_label": label},
                        {
                            "subject_key": key,
                            "grade": dec(grade),
                            "coefficient": dec(coef),
                            "credits": dec(credits),
                            "hours": hours,
                        },
                    )

    def seed_embedding_model(self) -> None:
        spec = dict(embedding.EMBEDDING_MODEL)
        lookup = {"name": spec.pop("name"), "revision": spec.pop("revision")}
        other_active = self.s.scalars(
            select(EmbeddingModel.id).where(
                EmbeddingModel.is_active,
                (EmbeddingModel.name != lookup["name"])
                | (EmbeddingModel.revision != lookup["revision"]),
            )
        ).first()
        if other_active is not None:
            # Un modèle actif existe déjà (choisi par E4) : on ne le remplace pas.
            spec["is_active"] = False
        self.get_or_create(EmbeddingModel, lookup, spec)

    def run(self) -> None:
        self.seed_accounts()
        self.seed_institutions()
        self.seed_roles()
        self.seed_programmes()
        self.seed_subjects()
        self.seed_curricula()
        self.seed_admission()
        self.seed_fees()
        self.seed_bridges()
        self.seed_candidates()
        self.seed_embedding_model()
        self.actor(None)


def installments(
    total: Decimal, count: int, discount: str, start_year: int
) -> list[tuple[int, date | None, str | None, Decimal]]:
    """Échéancier d'un plan (calcul par code, jamais par le LLM) : la somme est exacte.

    - 1 tranche : total remisé, à l'inscription ;
    - 3 tranches : 40 % à l'inscription, 30 % au 15/12, le solde au 15/03.
    """
    if count == 1:
        net = money(total * (Decimal(100) - Decimal(discount)) / Decimal(100))
        return [(1, None, "À l'inscription", net)]
    if count != 3:
        raise ValueError("Seuls les plans en 1 ou 3 tranches sont prévus dans le seed.")
    first = money((total * Decimal("0.4")).quantize(Decimal("1"), ROUND_HALF_UP))
    second = money((total * Decimal("0.3")).quantize(Decimal("1"), ROUND_HALF_UP))
    return [
        (1, None, "À l'inscription", first),
        (2, date(start_year, 12, 15), None, second),
        (3, date(start_year + 1, 3, 15), None, money(total - first - second)),
    ]


# ------------------------------------------------------------------------------------------------
# Récapitulatif, réinitialisation, point d'entrée
# ------------------------------------------------------------------------------------------------
def table_counts(session: Session) -> dict[str, int]:
    """Nombre de lignes par table du schéma E2 (ordre alphabétique)."""
    counts = {}
    for table in sorted(Base.metadata.tables):
        counts[table] = session.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one()
    return counts


def reset_database(migration_url: str) -> None:
    """`alembic downgrade base && alembic upgrade head` (rôle propriétaire) : EFFACE la base."""
    env = dict(os.environ, MIGRATION_DATABASE_URL=migration_url)
    for args in (["downgrade", "base"], ["upgrade", "head"]):
        print(f"→ alembic {' '.join(args)}")
        subprocess.run(
            [sys.executable, "-m", "alembic", *args], cwd=BACKEND_DIR, env=env, check=True
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Charge les données de démonstration synthétiques (SA-18), sans doublon."
    )
    parser.add_argument(
        "--database-url",
        help="URL de la base (rôle applicatif). Défaut : DATABASE_URL (.env ou environnement).",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="EFFACE la base (alembic downgrade base puis upgrade head) avant le seed : "
        "les lignes publiées sont figées et ne peuvent pas être supprimées autrement.",
    )
    parser.add_argument(
        "--migration-database-url",
        help="URL du rôle propriétaire pour --reset. Défaut : MIGRATION_DATABASE_URL.",
    )
    parser.add_argument("--quiet", action="store_true", help="N'affiche pas le récapitulatif.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    from app.core.config import get_settings

    settings = get_settings()
    url = args.database_url or settings.database_url
    if not url:
        print("ERREUR : aucune base indiquée (--database-url ou DATABASE_URL).", file=sys.stderr)
        return 2
    if settings.app_env == "prod":
        print("ERREUR : le seed de démonstration est interdit en production.", file=sys.stderr)
        return 2

    if args.reset:
        migration_url = args.migration_database_url or settings.migration_database_url
        if not migration_url:
            print("ERREUR : --reset exige MIGRATION_DATABASE_URL.", file=sys.stderr)
            return 2
        print("ATTENTION : --reset efface toute la base visée.")
        reset_database(migration_url)

    engine = create_engine(to_sync_url(url))
    try:
        with Session(engine) as session, session.begin():
            seeder = Seeder(session)
            seeder.run()
        with Session(engine) as session:
            counts = table_counts(session)
    except SQLAlchemyError as exc:
        print(f"ERREUR pendant le seed (aucune donnée écrite) : {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    created = sum(seeder.created.values())
    existing = sum(seeder.existing.values())
    print(f"Seed SA-18 terminé : {created} ligne(s) créée(s), {existing} déjà présente(s).")
    if not args.quiet:
        print(f"\n{'table':<34}{'créées':>8}{'lignes':>9}")
        for table, n in counts.items():
            if n or seeder.created[table]:
                print(f"{table:<34}{seeder.created[table]:>8}{n:>9}")
        print(f"{'total':<34}{created:>8}{sum(counts.values()):>9}")
        print("\nComptes de démo (auth simulée : en-têtes X-Dev-User-Id / X-Dev-Roles) :")
        for spec in accounts.STAFF.values():
            print(f"  {spec['email']:<30} {spec['id']}  {','.join(spec['roles'])}")
        for spec in candidates.CANDIDATES:
            print(f"  {spec['email']:<30} {spec['id']}  candidate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
