"""Rôles, comptes staff fictifs et identifiants fixes (SA-18).

Les UUID sont FIXES : ils restent identiques après `--reset`, si bien que les en-têtes de
l'authentification simulée (`X-Dev-User-Id`, `X-Dev-Institution-Id`) documentés dans le PDF
SA-18 restent valables. Préfixe `5eed0000-…` = « seed », facile à reconnaître dans les journaux.

Les comptes ne peuvent pas se connecter : `password_hash` contient un marqueur qui n'est pas un
hash Argon2id valide (l'authentification réelle est le travail d'E3).
"""

from __future__ import annotations

import uuid

#: Marqueur non vérifiable : aucune connexion par mot de passe possible avec les comptes seed.
NO_LOGIN_HASH = "!seed-sa18-pas-de-connexion"


def seed_uuid(n: int) -> uuid.UUID:
    """UUID fixe et lisible des objets de démo : 5eed0000-0000-4000-8000-<n sur 12 chiffres>."""
    return uuid.UUID(f"5eed0000-0000-4000-8000-{n:012d}")


# --- Institutions (identifiants fixes pour X-Dev-Institution-Id) --------------------------------
IIT_ID = seed_uuid(1001)
ISB_ID = seed_uuid(1002)

# --- Rôles (SA-3 staff_role + candidate ; périmètre institutionnel SA-13 D20) -------------------
ROLES: list[dict] = [
    {"code": "candidate", "label": "Candidat", "is_staff": False, "institution": None},
    {
        "code": "iit_academic_lead",
        "label": "Responsable académique IIT",
        "is_staff": True,
        "institution": "IIT",
    },
    {
        "code": "isb_academic_lead",
        "label": "Responsable académique ISB",
        "is_staff": True,
        "institution": "ISB",
    },
    {
        "code": "interview_lead",
        "label": "Responsable des entretiens",
        "is_staff": True,
        "institution": None,
    },
    {"code": "direction", "label": "Direction", "is_staff": True, "institution": None},
    {
        "code": "platform_admin",
        "label": "Administrateur de la plateforme",
        "is_staff": True,
        "institution": None,
    },
]

# --- Comptes staff fictifs ----------------------------------------------------------------------
# Clé = alias interne du seed (auteur / publieur des lignes du catalogue).
STAFF: dict[str, dict] = {
    "iit_a": {
        "id": seed_uuid(1),
        "email": "resp.iit.a@example.tn",
        "full_name": "Responsable IIT A (compte fictif)",
        "roles": ["iit_academic_lead"],
        "institution": "IIT",
        "usage": "Rédige et soumet le catalogue IIT (rédacteur).",
    },
    "iit_b": {
        "id": seed_uuid(2),
        "email": "resp.iit.b@example.tn",
        "full_name": "Responsable IIT B (compte fictif)",
        "roles": ["iit_academic_lead"],
        "institution": "IIT",
        "usage": "Relit et publie ce que A a soumis (quatre yeux).",
    },
    "isb": {
        "id": seed_uuid(3),
        "email": "resp.isb@example.tn",
        "full_name": "Responsable ISB (compte fictif)",
        "roles": ["isb_academic_lead"],
        "institution": "ISB",
        "usage": "Rédige et soumet le catalogue ISB ; la direction publie.",
    },
    "interview": {
        "id": seed_uuid(4),
        "email": "resp.entretiens@example.tn",
        "full_name": "Responsable des entretiens (compte fictif)",
        "roles": ["interview_lead"],
        "institution": None,
        "usage": "Créneaux, entretiens, banque de questions QCM.",
    },
    "direction": {
        "id": seed_uuid(5),
        "email": "direction@example.tn",
        "full_name": "Direction (compte fictif)",
        "roles": ["direction"],
        "institution": None,
        "usage": "Publie le catalogue ISB et les institutions ; décisions officielles.",
    },
    "admin": {
        "id": seed_uuid(6),
        "email": "admin.plateforme@example.tn",
        "full_name": "Administrateur plateforme (compte fictif)",
        "roles": ["platform_admin"],
        "institution": None,
        "usage": "Comptes, documents RAG (dépôt), supervision ; ne publie jamais (D-H).",
    },
}

#: Qui rédige/soumet et qui publie, par institution (D-H : un AUTRE responsable ou la direction).
PUBLICATION_PAIRS: dict[str, tuple[str, str]] = {
    "IIT": ("iit_a", "iit_b"),
    "ISB": ("isb", "direction"),
}
