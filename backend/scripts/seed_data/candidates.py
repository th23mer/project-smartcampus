"""Trois candidats fictifs (SA-18) : profils et relevés de bac de séries différentes.

Chaque profil illustre un verdict différent de `check_eligibility` (calcul par code, SA-21) :
- C1, bac Mathématiques, très bon dossier : éligible Licence info, Prépa MP, Licences IIT ;
- C2, bac Économie et gestion : non éligible aux formations IIT (série non acceptée),
  éligible aux Licences ISB ;
- C3, bac Sciences techniques + deux années de Licence ailleurs (réorientation) : éligible
  Prépa PT et Licence (entrée en 2e année, dossier d'équivalence), non éligible Prépa MP
  (moyenne < 12). Ses matières universitaires servent la démo d'équivalence (F4).

Notes, villes et dates de naissance sont inventées. Les clés de série et de matière sont les clés
françaises du référentiel (C1).
"""

from __future__ import annotations

from .accounts import seed_uuid

CANDIDATES: list[dict] = [
    {
        "id": seed_uuid(101),
        "email": "candidat.demo1@example.tn",
        "full_name": "Candidat démo 1 (fictif)",
        "preferred_language": "aeb_latn",
        "profile": {
            "candidate_type": "new_bachelor",
            "birth_date": "2008-04-12",
            "city": "Sfax",
            "interests": ["informatique", "intelligence artificielle", "robotique"],
            "goals": "Devenir ingénieur en informatique, idéalement dans l'IA.",
            "constraints": {"budget_annuel_max_tnd": "8500.000", "mobilite": "Sfax uniquement"},
            "profile_status": "confirmed",
            "field_sources": {
                "interests": "ai_extracted",
                "goals": "ai_extracted",
                "constraints": "declared",
            },
        },
        "records": [
            {
                "record_type": "bac",
                "bac_section": "mathematiques",
                "year": 2026,
                "institution_name": "Lycée public (fictif)",
                "diploma_label": "Baccalauréat Mathématiques",
                "overall_average": "14.32",
                "orientation_score": "156.480",
                "subjects": [
                    ("Mathématiques", "mathematiques", "15.50", "4"),
                    ("Physique", "physique", "14.00", "4"),
                    ("Sciences de la vie et de la terre", "sciences_vie_terre", "12.50", "1"),
                    ("Informatique", "informatique", "16.00", "1"),
                    ("Français", "francais", "12.00", "1"),
                    ("Anglais", "anglais", "14.00", "1"),
                    ("Arabe", "arabe", "11.50", "1"),
                    ("Philosophie", "philosophie", "10.50", "1"),
                ],
            }
        ],
    },
    {
        "id": seed_uuid(102),
        "email": "candidat.demo2@example.tn",
        "full_name": "Candidat démo 2 (fictif)",
        "preferred_language": "fr",
        "profile": {
            "candidate_type": "new_bachelor",
            "birth_date": "2008-09-30",
            "city": "Sousse",
            "interests": ["marketing digital", "commerce international", "langues"],
            "goals": "Travailler dans le marketing digital ou le commerce à l'international.",
            "constraints": {"budget_annuel_max_tnd": "6000.000", "paiement": "en tranches"},
            "profile_status": "ai_draft",
            "field_sources": {
                "interests": "ai_extracted",
                "goals": "ai_extracted",
                "constraints": "ai_extracted",
            },
        },
        "records": [
            {
                "record_type": "bac",
                "bac_section": "economie_gestion",
                "year": 2026,
                "institution_name": "Lycée public (fictif)",
                "diploma_label": "Baccalauréat Économie et gestion",
                "overall_average": "12.85",
                "orientation_score": "138.200",
                "subjects": [
                    ("Économie", "economie", "14.00", "3"),
                    ("Gestion", "gestion", "13.50", "3"),
                    ("Mathématiques", "mathematiques", "11.00", "2"),
                    ("Histoire-géographie", "histoire_geographie", "12.00", "1"),
                    ("Informatique", "informatique", "13.00", "1"),
                    ("Français", "francais", "13.00", "1"),
                    ("Anglais", "anglais", "15.00", "1"),
                    ("Arabe", "arabe", "12.00", "1"),
                    ("Philosophie", "philosophie", "11.00", "1"),
                ],
            }
        ],
    },
    {
        "id": seed_uuid(103),
        "email": "candidat.demo3@example.tn",
        "full_name": "Candidat démo 3 (fictif)",
        "preferred_language": "aeb_arab",
        "profile": {
            "candidate_type": "transfer",
            "birth_date": "2006-01-21",
            "city": "Gabès",
            "interests": ["électronique", "systèmes embarqués", "énergie"],
            "goals": "Se réorienter vers un parcours ingénieur après deux années de Licence.",
            "constraints": {"budget_annuel_max_tnd": "7500.000", "alternance": "souhaitée"},
            "profile_status": "confirmed",
            "field_sources": {
                "interests": "declared",
                "goals": "ai_extracted",
                "constraints": "declared",
            },
        },
        "records": [
            {
                "record_type": "bac",
                "bac_section": "sciences_techniques",
                "year": 2024,
                "institution_name": "Lycée technique (fictif)",
                "diploma_label": "Baccalauréat Sciences techniques",
                "overall_average": "11.40",
                "orientation_score": "121.050",
                "subjects": [
                    ("Mathématiques", "mathematiques", "10.25", "3"),
                    ("Physique", "physique", "11.50", "3"),
                    ("Technologie", "technologie", "13.00", "3"),
                    ("Informatique", "informatique", "12.00", "1"),
                    ("Français", "francais", "10.00", "1"),
                    ("Anglais", "anglais", "11.50", "1"),
                    ("Arabe", "arabe", "10.50", "1"),
                    ("Philosophie", "philosophie", "9.00", "1"),
                ],
            },
            {
                # Relevé universitaire : matières libres (pas de clé de bac), crédits et heures
                # pour l'assistant d'équivalence (F4).
                "record_type": "university_year",
                "bac_section": None,
                "year": 2025,
                "institution_name": "Université publique (fictive)",
                "diploma_label": "Licence en génie électrique, 1re année (L1)",
                "overall_average": "11.80",
                "orientation_score": None,
                "subjects": [
                    ("Analyse mathématique 1", None, "11.00", "3", "6", 63),
                    ("Algèbre 1", None, "10.50", "2", "4", 42),
                    ("Électricité générale", None, "12.75", "3", "6", 63),
                    ("Électronique analogique 1", None, "12.00", "3", "6", 56),
                    ("Programmation en langage C", None, "13.25", "2", "5", 49),
                    ("Anglais technique", None, "12.50", "1", "3", 21),
                ],
            },
            {
                "record_type": "university_year",
                "bac_section": None,
                "year": 2026,
                "institution_name": "Université publique (fictive)",
                "diploma_label": "Licence en génie électrique, 2e année (L2)",
                "overall_average": "10.90",
                "orientation_score": None,
                "subjects": [
                    ("Analyse mathématique 2", None, "10.00", "3", "6", 63),
                    ("Électronique numérique", None, "11.50", "3", "6", 56),
                    ("Machines électriques", None, "10.25", "3", "6", 56),
                    ("Microcontrôleurs", None, "12.00", "2", "5", 49),
                    ("Probabilités et statistiques", None, "9.75", "2", "4", 42),
                    ("Communication professionnelle", None, "13.00", "1", "3", 21),
                ],
            },
        ],
    },
]
