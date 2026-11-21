"""Catalogue académique synthétique « réaliste moyen » (SA-18, décision étape B du 17/11).

IIT : 4 Licences (+ 1 brouillon), 2 Prépas intégrées, cycle Ingénieur (5 spécialités publiées
+ 1 en relecture) ; ISB : 3 programmes. Cursus avec matières, semestres, crédits et prérequis ;
conditions d'admission par rentrée (2026-2027 et 2027-2028) avec notes minimales par matière du
bac (clés françaises, C1) ; frais 2026-2027 publiés, 2027-2028 en relecture (pending_review) ;
passerelles pour le Path Explorer.

Cas de démonstration du filtrage « publié et valide à la date D » :
- brouillons : formation LIC-IA, grille 2027-2028 de la spécialité GINFO, conditions 2027-2028
  de LIC-MECA ;
- en relecture : spécialité ING/IADS, frais 2027-2028, conditions 2027-2028 de LIC-GC,
  passerelle LIC-COMM → MP-MGT ;
- expirés (publiés mais `valid_to` passé) : frais 2025-2026 (LIC-INFO, ING), conditions
  2025-2026 de LIC-INFO, ancienne maquette v2022 du cursus LIC-INFO/GL ;
- archivés : frais 2024-2025 de LIC-INFO, ancienne passerelle LIC-INFO → ING (sans spécialité).

Statut `expired` (seed seulement) = publié avec `valid_to` dans le passé.
Montants en dinars (TND), chaînes décimales à 3 décimales, tous inventés.
"""

from __future__ import annotations

from .accounts import IIT_ID, ISB_ID

# ================================================================================================
# Institutions, formations, spécialités
# ================================================================================================

INSTITUTIONS: list[dict] = [
    {
        "id": IIT_ID,
        "code": "IIT",
        "name_fr": "Institut International de Technologie",
        "name_ar": "المعهد الدولي للتكنولوجيا",
        "city": "Sfax",
        "website_url": "https://iit.example.tn",
        "description_fr": (
            "École privée d'ingénieurs et de technologie : Licences, cycle préparatoire intégré "
            "et cycle ingénieur. (Données de démonstration fictives.)"
        ),
        "status": "published",
        "valid_from": "2015-09-01",
    },
    {
        "id": ISB_ID,
        "code": "ISB",
        "name_fr": "Institut Supérieur de Business",
        "name_ar": "المعهد العالي للأعمال",
        "city": "Sfax",
        "website_url": "https://isb.example.tn",
        "description_fr": (
            "École privée de gestion, commerce et management : Licences et master professionnel. "
            "(Données de démonstration fictives.)"
        ),
        "status": "published",
        "valid_from": "2017-09-01",
    },
]

PROGRAMMES: list[dict] = [
    # --- IIT : Licences ---
    {
        "code": "LIC-INFO",
        "institution": "IIT",
        "name_fr": "Licence en informatique",
        "name_ar": "الإجازة في الإعلامية",
        "programme_type": "licence",
        "diploma_name_fr": "Licence en sciences de l'informatique",
        "duration_years": 3,
        "total_ects": 180,
        "description_fr": (
            "Programmation, algorithmique, bases de données, réseaux et génie logiciel ; "
            "projet de fin d'études en entreprise au 6e semestre."
        ),
        "career_outcomes_fr": (
            "Développeur web ou mobile, administrateur de bases de données, technicien réseaux ; "
            "poursuite en cycle ingénieur (passerelle) ou en master."
        ),
        "status": "published",
        "valid_from": "2018-09-01",
    },
    {
        "code": "LIC-ELEC",
        "institution": "IIT",
        "name_fr": "Licence en génie électrique",
        "name_ar": "الإجازة في الهندسة الكهربائية",
        "programme_type": "licence",
        "diploma_name_fr": "Licence en génie électrique",
        "duration_years": 3,
        "total_ects": 180,
        "description_fr": (
            "Électronique, électrotechnique, automatique et systèmes embarqués, avec de nombreux "
            "travaux pratiques."
        ),
        "career_outcomes_fr": (
            "Technicien supérieur en électronique, maintenance industrielle, systèmes embarqués ; "
            "poursuite en cycle ingénieur."
        ),
        "status": "published",
        "valid_from": "2018-09-01",
    },
    {
        "code": "LIC-MECA",
        "institution": "IIT",
        "name_fr": "Licence en génie mécanique",
        "name_ar": "الإجازة في الهندسة الميكانيكية",
        "programme_type": "licence",
        "diploma_name_fr": "Licence en génie mécanique",
        "duration_years": 3,
        "total_ects": 180,
        "description_fr": (
            "Mécanique, résistance des matériaux, conception assistée et fabrication."
        ),
        "career_outcomes_fr": "Conception mécanique, production, maintenance, bureau d'études.",
        "status": "published",
        "valid_from": "2019-09-01",
    },
    {
        "code": "LIC-GC",
        "institution": "IIT",
        "name_fr": "Licence en génie civil",
        "name_ar": "الإجازة في الهندسة المدنية",
        "programme_type": "licence",
        "diploma_name_fr": "Licence en génie civil",
        "duration_years": 3,
        "total_ects": 180,
        "description_fr": (
            "Matériaux de construction, topographie, structures et suivi de chantier."
        ),
        "career_outcomes_fr": "Conducteur de travaux, technicien en bureau d'études, métreur.",
        "status": "published",
        "valid_from": "2019-09-01",
    },
    {
        # Brouillon : invisible pour l'agent et le site public (démo du filtrage).
        "code": "LIC-IA",
        "institution": "IIT",
        "name_fr": "Licence en intelligence artificielle et science des données",
        "name_ar": "الإجازة في الذكاء الاصطناعي وعلوم البيانات",
        "programme_type": "licence",
        "diploma_name_fr": "Licence en science des données",
        "duration_years": 3,
        "total_ects": 180,
        "description_fr": "Projet de nouvelle Licence, en cours de rédaction.",
        "career_outcomes_fr": None,
        "status": "draft",
        "valid_from": "2027-09-01",
    },
    # --- IIT : Prépas intégrées ---
    {
        "code": "PREPA-MP",
        "institution": "IIT",
        "name_fr": "Cycle préparatoire intégré Mathématiques-Physique",
        "name_ar": "المرحلة التحضيرية المندمجة رياضيات-فيزياء",
        "programme_type": "preparatory",
        "diploma_name_fr": "Attestation de réussite du cycle préparatoire intégré",
        "duration_years": 2,
        "total_ects": 120,
        "description_fr": (
            "Deux années intensives de mathématiques, physique et informatique ; accès direct au "
            "cycle ingénieur de l'IIT si les deux années sont validées."
        ),
        "career_outcomes_fr": "Cycle ingénieur de l'IIT (passage automatique) ou autres écoles.",
        "status": "published",
        "valid_from": "2018-09-01",
    },
    {
        "code": "PREPA-PT",
        "institution": "IIT",
        "name_fr": "Cycle préparatoire intégré Physique-Technologie",
        "name_ar": "المرحلة التحضيرية المندمجة فيزياء-تكنولوجيا",
        "programme_type": "preparatory",
        "diploma_name_fr": "Attestation de réussite du cycle préparatoire intégré",
        "duration_years": 2,
        "total_ects": 120,
        "description_fr": (
            "Prépa orientée sciences de l'ingénieur et technologie, adaptée aux bacheliers "
            "Sciences techniques ; accès au cycle ingénieur de l'IIT."
        ),
        "career_outcomes_fr": "Cycle ingénieur de l'IIT (génie électrique, mécanique, civil).",
        "status": "published",
        "valid_from": "2020-09-01",
    },
    # --- IIT : cycle ingénieur ---
    {
        "code": "ING",
        "institution": "IIT",
        "name_fr": "Cycle ingénieur",
        "name_ar": "مرحلة تكوين المهندسين",
        "programme_type": "engineering",
        "diploma_name_fr": "Diplôme national d'ingénieur",
        "duration_years": 3,
        "total_ects": 180,
        "description_fr": (
            "Trois années de formation d'ingénieur dans l'une des spécialités, stage d'ingénieur "
            "et projet de fin d'études en entreprise."
        ),
        "career_outcomes_fr": (
            "Ingénieur en informatique, électrique, mécanique, civil ou industriel ; chef de "
            "projet, ingénieur R&D, consultant."
        ),
        "status": "published",
        "valid_from": "2018-09-01",
    },
    # --- ISB ---
    {
        "code": "LIC-GEST",
        "institution": "ISB",
        "name_fr": "Licence en sciences de gestion",
        "name_ar": "الإجازة في علوم التصرف",
        "programme_type": "licence",
        "diploma_name_fr": "Licence en sciences de gestion",
        "duration_years": 3,
        "total_ects": 180,
        "description_fr": (
            "Comptabilité, finance, marketing, ressources humaines et contrôle de gestion ; "
            "spécialisation en 2e année (Finance ou Marketing)."
        ),
        "career_outcomes_fr": (
            "Assistant comptable ou financier, chargé de marketing, gestionnaire RH ; poursuite "
            "en master."
        ),
        "status": "published",
        "valid_from": "2017-09-01",
    },
    {
        "code": "LIC-COMM",
        "institution": "ISB",
        "name_fr": "Licence en commerce international et e-business",
        "name_ar": "الإجازة في التجارة الدولية والأعمال الإلكترونية",
        "programme_type": "licence",
        "diploma_name_fr": "Licence en commerce international",
        "duration_years": 3,
        "total_ects": 180,
        "description_fr": (
            "Commerce international, logistique, e-commerce, négociation et langues des affaires."
        ),
        "career_outcomes_fr": (
            "Assistant export, e-commerce manager, chargé de clientèle internationale."
        ),
        "status": "published",
        "valid_from": "2019-09-01",
    },
    {
        "code": "MP-MGT",
        "institution": "ISB",
        "name_fr": "Master professionnel en management digital",
        "name_ar": "الماجستير المهني في الإدارة الرقمية",
        "programme_type": "master",
        "diploma_name_fr": "Master professionnel en management",
        "duration_years": 2,
        "total_ects": 120,
        "description_fr": (
            "Stratégie, transformation digitale, leadership et analyse de données pour "
            "titulaires d'une Licence."
        ),
        "career_outcomes_fr": "Chef de projet digital, consultant, responsable d'unité.",
        "status": "published",
        "valid_from": "2021-09-01",
    },
]

SPECIALITIES: list[dict] = [
    {
        "programme": "LIC-INFO",
        "code": "GL",
        "name_fr": "Génie logiciel",
        "name_ar": "هندسة البرمجيات",
        "description_fr": "Conception et développement d'applications web, mobiles et métiers.",
        "career_outcomes_fr": "Développeur full stack, testeur, analyste-programmeur.",
        "status": "published",
        "valid_from": "2018-09-01",
    },
    {
        "programme": "LIC-INFO",
        "code": "SIR",
        "name_fr": "Systèmes informatiques et réseaux",
        "name_ar": "الأنظمة المعلوماتية والشبكات",
        "description_fr": "Administration systèmes, réseaux, sécurité et cloud.",
        "career_outcomes_fr": "Administrateur systèmes et réseaux, technicien cloud.",
        "status": "published",
        "valid_from": "2018-09-01",
    },
    {
        "programme": "LIC-ELEC",
        "code": "SE",
        "name_fr": "Systèmes embarqués et objets connectés",
        "name_ar": "الأنظمة المدمجة والأشياء المتصلة",
        "description_fr": "Microcontrôleurs, capteurs, programmation embarquée et IoT.",
        "career_outcomes_fr": "Technicien en systèmes embarqués, intégrateur IoT.",
        "status": "published",
        "valid_from": "2020-09-01",
    },
    {
        "programme": "LIC-GEST",
        "code": "FIN",
        "name_fr": "Finance",
        "name_ar": "المالية",
        "description_fr": "Finance d'entreprise, marchés financiers, fiscalité.",
        "career_outcomes_fr": "Assistant financier, chargé de clientèle bancaire.",
        "status": "published",
        "valid_from": "2017-09-01",
    },
    {
        "programme": "LIC-GEST",
        "code": "MKT",
        "name_fr": "Marketing",
        "name_ar": "التسويق",
        "description_fr": "Marketing stratégique et digital, études de marché, relation client.",
        "career_outcomes_fr": "Chargé de marketing, community manager, chargé d'études.",
        "status": "published",
        "valid_from": "2017-09-01",
    },
    {
        "programme": "ING",
        "code": "GINFO",
        "name_fr": "Génie informatique",
        "name_ar": "الهندسة الإعلامية",
        "description_fr": (
            "Architecture logicielle, données et intelligence artificielle, cloud et sécurité."
        ),
        "career_outcomes_fr": "Ingénieur logiciel, data scientist, architecte cloud.",
        "status": "published",
        "valid_from": "2018-09-01",
    },
    {
        "programme": "ING",
        "code": "GELEC",
        "name_fr": "Génie électrique",
        "name_ar": "الهندسة الكهربائية",
        "description_fr": "Automatique, électronique de puissance, énergies renouvelables, IoT.",
        "career_outcomes_fr": "Ingénieur automaticien, ingénieur énergie, ingénieur R&D.",
        "status": "published",
        "valid_from": "2018-09-01",
    },
    {
        "programme": "ING",
        "code": "GMECA",
        "name_fr": "Génie mécanique",
        "name_ar": "الهندسة الميكانيكية",
        "description_fr": "Conception, simulation numérique, fabrication et maintenance.",
        "career_outcomes_fr": "Ingénieur conception, ingénieur production.",
        "status": "published",
        "valid_from": "2019-09-01",
    },
    {
        "programme": "ING",
        "code": "GCIV",
        "name_fr": "Génie civil",
        "name_ar": "الهندسة المدنية",
        "description_fr": "Structures, géotechnique, hydraulique et gestion de projets de BTP.",
        "career_outcomes_fr": "Ingénieur structures, ingénieur travaux.",
        "status": "published",
        "valid_from": "2019-09-01",
    },
    {
        "programme": "ING",
        "code": "GIND",
        "name_fr": "Génie industriel",
        "name_ar": "الهندسة الصناعية",
        "description_fr": "Logistique, qualité, optimisation des systèmes de production.",
        "career_outcomes_fr": "Ingénieur méthodes, ingénieur qualité, supply chain.",
        "status": "published",
        "valid_from": "2021-09-01",
    },
    {
        # En relecture : soumise par le responsable IIT A, à publier par B (démo quatre yeux).
        "programme": "ING",
        "code": "IADS",
        "name_fr": "Intelligence artificielle et science des données",
        "name_ar": "الذكاء الاصطناعي وعلوم البيانات",
        "description_fr": "Nouvelle spécialité proposée pour la rentrée 2027-2028.",
        "career_outcomes_fr": "Ingénieur IA, data engineer, ingénieur MLOps.",
        "status": "pending_review",
        "valid_from": "2027-09-01",
    },
]

# ================================================================================================
# Matières (référentiel interne par institution)
# ================================================================================================
# (code, nom, domaine, nature, description) ; la nature sert à répartir les heures :
#   cours = CM + TD ; tp = CM + TD + TP ; langue = TD seul ; projet = encadrement (TP).

_IIT_SUBJECTS = [
    # Mathématiques
    (
        "ANA1",
        "Analyse 1",
        "mathematiques",
        "cours",
        "Suites, fonctions d'une variable réelle, limites, continuité, dérivation, "
        "développements limités.",
    ),
    (
        "ANA2",
        "Analyse 2",
        "mathematiques",
        "cours",
        "Intégration, séries numériques, équations différentielles, fonctions de plusieurs "
        "variables.",
    ),
    (
        "ALG1",
        "Algèbre 1",
        "mathematiques",
        "cours",
        "Logique, ensembles, nombres complexes, polynômes, introduction aux espaces vectoriels.",
    ),
    (
        "ALG2",
        "Algèbre linéaire",
        "mathematiques",
        "cours",
        "Matrices, applications linéaires, déterminants, réduction et diagonalisation.",
    ),
    (
        "PROBA",
        "Probabilités et statistiques",
        "mathematiques",
        "cours",
        "Variables aléatoires, lois usuelles, estimation, intervalles de confiance, tests.",
    ),
    (
        "MDISC",
        "Mathématiques discrètes",
        "mathematiques",
        "cours",
        "Logique des propositions, combinatoire, relations, théorie des graphes.",
    ),
    (
        "ANUM",
        "Analyse numérique",
        "mathematiques",
        "tp",
        "Résolution numérique d'équations, interpolation, intégration numérique, méthodes "
        "itératives.",
    ),
    (
        "RO",
        "Recherche opérationnelle",
        "mathematiques",
        "cours",
        "Programmation linéaire, simplexe, graphes et flots, optimisation combinatoire.",
    ),
    # Informatique
    (
        "ALGO1",
        "Algorithmique et structures de données 1",
        "informatique",
        "tp",
        "Algorithmes séquentiels, tableaux, chaînes, enregistrements, complexité, tris simples.",
    ),
    (
        "ALGO2",
        "Algorithmique et structures de données 2",
        "informatique",
        "tp",
        "Récursivité, listes chaînées, piles, files, arbres binaires, tris avancés.",
    ),
    (
        "PROGC",
        "Programmation en C",
        "informatique",
        "tp",
        "Syntaxe du C, pointeurs, allocation dynamique, fichiers, compilation séparée.",
    ),
    (
        "POO",
        "Programmation orientée objet (Java)",
        "informatique",
        "tp",
        "Classes, héritage, polymorphisme, interfaces, exceptions, collections.",
    ),
    (
        "ARCHI",
        "Architecture des ordinateurs",
        "informatique",
        "cours",
        "Représentation des données, logique booléenne, processeur, mémoire, assembleur.",
    ),
    (
        "SYSEXP",
        "Systèmes d'exploitation",
        "informatique",
        "tp",
        "Processus, ordonnancement, mémoire virtuelle, systèmes de fichiers, shell Linux.",
    ),
    (
        "BD1",
        "Bases de données",
        "informatique",
        "tp",
        "Modèle relationnel, SQL, conception entité-association, normalisation.",
    ),
    (
        "BD2",
        "Bases de données avancées",
        "informatique",
        "tp",
        "Transactions, index, optimisation de requêtes, bases NoSQL.",
    ),
    (
        "RES1",
        "Réseaux informatiques",
        "informatique",
        "tp",
        "Modèles OSI et TCP/IP, adressage IP, routage, services réseau.",
    ),
    (
        "WEB",
        "Technologies et programmation web",
        "informatique",
        "tp",
        "HTML, CSS, JavaScript, API REST, framework côté serveur.",
    ),
    (
        "GL1",
        "Génie logiciel et UML",
        "informatique",
        "cours",
        "Cycle de vie du logiciel, exigences, modélisation UML, tests.",
    ),
    (
        "AGILE",
        "Méthodes agiles et qualité logicielle",
        "informatique",
        "tp",
        "Scrum, intégration continue, tests automatisés, revue de code.",
    ),
    (
        "MOB",
        "Développement mobile",
        "informatique",
        "tp",
        "Applications mobiles multiplateformes, cycle de vie, stockage local, API.",
    ),
    (
        "IA1",
        "Introduction à l'intelligence artificielle",
        "informatique",
        "tp",
        "Recherche heuristique, apprentissage supervisé, évaluation de modèles.",
    ),
    (
        "CLOUD",
        "Cloud et DevOps",
        "informatique",
        "tp",
        "Conteneurs, orchestration, pipelines CI/CD, supervision.",
    ),
    (
        "SECU",
        "Sécurité informatique",
        "informatique",
        "tp",
        "Cryptographie appliquée, sécurité des applications web, gestion des identités.",
    ),
    (
        "COMPIL",
        "Théorie des langages et compilation",
        "informatique",
        "cours",
        "Automates, grammaires, analyse lexicale et syntaxique.",
    ),
    (
        "ML",
        "Apprentissage automatique",
        "informatique",
        "tp",
        "Régression, classification, arbres, méthodes d'ensemble, validation croisée.",
    ),
    (
        "DL",
        "Apprentissage profond",
        "informatique",
        "tp",
        "Réseaux de neurones, réseaux convolutifs et récurrents, transformeurs.",
    ),
    (
        "BIGDATA",
        "Big data et traitement distribué",
        "informatique",
        "tp",
        "Stockage distribué, traitement par lots et en flux, entrepôts de données.",
    ),
    (
        "ARCHLOG",
        "Architectures logicielles et microservices",
        "informatique",
        "tp",
        "Patrons d'architecture, microservices, API, messagerie asynchrone.",
    ),
    (
        "SYSDIST",
        "Systèmes distribués",
        "informatique",
        "cours",
        "Communication, cohérence, tolérance aux pannes, consensus.",
    ),
    (
        "NLP",
        "Traitement automatique du langage (option)",
        "informatique",
        "tp",
        "Représentations de textes, classification, modèles de langue.",
    ),
    (
        "VISION",
        "Vision par ordinateur (option)",
        "informatique",
        "tp",
        "Traitement d'images, détection et segmentation d'objets.",
    ),
    (
        "IOT",
        "Internet des objets",
        "informatique",
        "tp",
        "Capteurs, protocoles IoT, plateformes et sécurité des objets connectés.",
    ),
    (
        "MLOPS",
        "MLOps et industrialisation des modèles",
        "informatique",
        "tp",
        "Suivi d'expériences, déploiement, supervision et réentraînement des modèles.",
    ),
    (
        "DATAVIZ",
        "Visualisation de données",
        "informatique",
        "tp",
        "Principes de visualisation, tableaux de bord, narration par les données.",
    ),
    (
        "IAETH",
        "IA responsable et éthique",
        "informatique",
        "cours",
        "Biais, explicabilité, protection des données, cadre réglementaire.",
    ),
    # Sciences de base (prépa) et sciences de l'ingénieur
    (
        "ANA-P1",
        "Analyse (prépa) 1",
        "mathematiques",
        "cours",
        "Nombres réels, suites, fonctions, dérivation et intégration.",
    ),
    (
        "ANA-P2",
        "Analyse (prépa) 2",
        "mathematiques",
        "cours",
        "Séries, intégrales généralisées, équations différentielles linéaires.",
    ),
    (
        "ANA-P3",
        "Analyse (prépa) 3",
        "mathematiques",
        "cours",
        "Suites et séries de fonctions, séries entières, fonctions de plusieurs variables.",
    ),
    (
        "ANA-P4",
        "Analyse (prépa) 4",
        "mathematiques",
        "cours",
        "Intégrales multiples, séries de Fourier, calcul différentiel.",
    ),
    (
        "ALG-P1",
        "Algèbre (prépa) 1",
        "mathematiques",
        "cours",
        "Structures algébriques, polynômes, arithmétique.",
    ),
    (
        "ALG-P2",
        "Algèbre (prépa) 2",
        "mathematiques",
        "cours",
        "Espaces vectoriels, applications linéaires, matrices.",
    ),
    (
        "ALG-P3",
        "Algèbre (prépa) 3",
        "mathematiques",
        "cours",
        "Réduction des endomorphismes, espaces euclidiens.",
    ),
    (
        "MECA",
        "Mécanique du point",
        "physique",
        "cours",
        "Cinématique, dynamique, énergie, oscillateurs.",
    ),
    (
        "MECA2",
        "Mécanique du solide",
        "physique",
        "cours",
        "Torseurs, cinétique et dynamique du solide.",
    ),
    (
        "ELEC",
        "Électricité et électromagnétisme",
        "physique",
        "tp",
        "Circuits, régime sinusoïdal, électrostatique, magnétostatique.",
    ),
    (
        "ELEC2",
        "Électromagnétisme et ondes",
        "physique",
        "cours",
        "Équations de Maxwell, propagation des ondes.",
    ),
    (
        "THERMO",
        "Thermodynamique",
        "physique",
        "cours",
        "Premier et second principes, machines thermiques.",
    ),
    (
        "OPTQ",
        "Optique et ondes",
        "physique",
        "tp",
        "Optique géométrique, interférences, diffraction.",
    ),
    ("CHIM", "Chimie générale", "chimie", "tp", "Atomistique, liaisons chimiques, thermochimie."),
    (
        "CHIM2",
        "Chimie des solutions",
        "chimie",
        "tp",
        "Équilibres acido-basiques, oxydoréduction, précipitation.",
    ),
    (
        "PYTHON",
        "Informatique : programmation Python",
        "informatique",
        "tp",
        "Types, structures de contrôle, fonctions, listes, fichiers en Python.",
    ),
    (
        "PYTHON2",
        "Informatique : algorithmique et bases de données",
        "informatique",
        "tp",
        "Algorithmes classiques, complexité, requêtes SQL.",
    ),
    (
        "SI",
        "Sciences de l'ingénieur",
        "sciences_ingenieur",
        "tp",
        "Analyse fonctionnelle, chaînes d'énergie et d'information, asservissements.",
    ),
    (
        "TECHDES",
        "Dessin technique",
        "sciences_ingenieur",
        "tp",
        "Normes du dessin industriel, projections, cotation.",
    ),
    (
        "ELN1",
        "Électronique analogique",
        "electrique",
        "tp",
        "Diodes, transistors, amplificateurs opérationnels.",
    ),
    (
        "ELN2",
        "Électronique de puissance",
        "electrique",
        "tp",
        "Convertisseurs statiques, hacheurs, onduleurs.",
    ),
    (
        "ELT1",
        "Électrotechnique",
        "electrique",
        "tp",
        "Circuits triphasés, transformateurs, machines électriques.",
    ),
    (
        "LOGIQ",
        "Logique combinatoire et séquentielle",
        "electrique",
        "tp",
        "Algèbre de Boole, bascules, compteurs, machines à états.",
    ),
    (
        "MICROC",
        "Microcontrôleurs et systèmes embarqués",
        "electrique",
        "tp",
        "Architecture d'un microcontrôleur, entrées-sorties, interruptions, C embarqué.",
    ),
    (
        "AUTO",
        "Automatique",
        "electrique",
        "cours",
        "Systèmes linéaires, fonctions de transfert, stabilité, correcteurs PID.",
    ),
    (
        "SIGNAL",
        "Traitement du signal",
        "electrique",
        "tp",
        "Transformée de Fourier, échantillonnage, filtrage numérique.",
    ),
    (
        "CMD",
        "Commande des systèmes",
        "electrique",
        "tp",
        "Représentation d'état, commande numérique, observateurs.",
    ),
    (
        "RESIND",
        "Réseaux industriels",
        "electrique",
        "tp",
        "Bus de terrain, automates programmables, supervision industrielle.",
    ),
    (
        "ENERG",
        "Énergies renouvelables",
        "electrique",
        "cours",
        "Solaire photovoltaïque, éolien, stockage, intégration au réseau.",
    ),
    (
        "MECAG",
        "Mécanique générale",
        "mecanique",
        "cours",
        "Statique, cinématique et dynamique des systèmes.",
    ),
    (
        "RDM",
        "Résistance des matériaux",
        "mecanique",
        "cours",
        "Contraintes, déformations, traction, flexion, torsion.",
    ),
    (
        "MATER",
        "Science des matériaux",
        "mecanique",
        "tp",
        "Structure des matériaux, propriétés mécaniques, essais.",
    ),
    (
        "CAO",
        "Dessin technique et CAO",
        "mecanique",
        "tp",
        "Modélisation 3D, mise en plan, assemblages.",
    ),
    ("TOPO", "Topographie", "genie_civil", "tp", "Instruments, nivellement, levés, implantation."),
    (
        "MATCON",
        "Matériaux de construction",
        "genie_civil",
        "tp",
        "Granulats, liants, bétons, essais normalisés.",
    ),
    # Langues, transversal, projets
    ("ANG1", "Anglais 1", "langues", "langue", "Anglais général, niveau B1."),
    ("ANG2", "Anglais 2", "langues", "langue", "Anglais scientifique et technique."),
    (
        "ANG3",
        "Anglais professionnel",
        "langues",
        "langue",
        "Communication professionnelle, préparation à une certification.",
    ),
    (
        "FR",
        "Techniques de communication",
        "langues",
        "langue",
        "Expression écrite et orale, rapports, présentations.",
    ),
    (
        "ENTR",
        "Entrepreneuriat et gestion de projet",
        "transversal",
        "cours",
        "Idée, modèle d'affaires, planification, travail en équipe.",
    ),
    (
        "GESTPROJ",
        "Management de projets",
        "transversal",
        "cours",
        "Planification, coûts, risques, pilotage d'équipe.",
    ),
    (
        "SOFT",
        "Soft skills et insertion professionnelle",
        "transversal",
        "langue",
        "Prise de parole, entretien d'embauche, éthique professionnelle.",
    ),
    (
        "RECH",
        "Initiation à la recherche",
        "transversal",
        "projet",
        "Bibliographie, méthode expérimentale, rédaction scientifique.",
    ),
    (
        "STAGE-INIT",
        "Stage d'initiation",
        "projet",
        "projet",
        "Stage d'un mois en entreprise, rapport et soutenance.",
    ),
    (
        "PROJ-INT",
        "Projet intégré",
        "projet",
        "projet",
        "Projet en équipe de la conception au déploiement.",
    ),
    (
        "PROJ-PREPA",
        "Travail d'initiative personnelle encadré",
        "projet",
        "projet",
        "Projet scientifique encadré, présentation orale.",
    ),
    (
        "PROJ-ING",
        "Projet d'ingénierie",
        "projet",
        "projet",
        "Projet d'ingénieur en équipe sur un besoin industriel.",
    ),
    (
        "STAGE-ING",
        "Stage d'ingénieur",
        "projet",
        "projet",
        "Stage de deux mois en entreprise, rapport et soutenance.",
    ),
    (
        "PFE-LIC",
        "Projet de fin d'études (Licence)",
        "projet",
        "projet",
        "Stage de fin d'études de quatre mois, mémoire et soutenance.",
    ),
    (
        "PFE-ING",
        "Projet de fin d'études (ingénieur)",
        "projet",
        "projet",
        "Projet de fin d'études de six mois en entreprise, mémoire et soutenance.",
    ),
]

_ISB_SUBJECTS = [
    (
        "PGE",
        "Principes de gestion",
        "gestion",
        "cours",
        "L'entreprise, ses fonctions, son environnement, les décisions de gestion.",
    ),
    (
        "MICRO",
        "Microéconomie",
        "economie",
        "cours",
        "Consommateur, producteur, marchés, concurrence.",
    ),
    (
        "MACRO",
        "Macroéconomie",
        "economie",
        "cours",
        "Agrégats, croissance, inflation, politiques économiques.",
    ),
    (
        "CPT1",
        "Comptabilité financière 1",
        "comptabilite",
        "cours",
        "Principes comptables, journal, grand livre, balance.",
    ),
    (
        "CPT2",
        "Comptabilité financière 2",
        "comptabilite",
        "cours",
        "Opérations de fin d'exercice, états financiers.",
    ),
    (
        "MATHG",
        "Mathématiques appliquées à la gestion",
        "mathematiques",
        "cours",
        "Fonctions, mathématiques financières, optimisation simple.",
    ),
    (
        "STATG",
        "Statistiques appliquées",
        "mathematiques",
        "tp",
        "Statistique descriptive, probabilités, échantillonnage, tableur.",
    ),
    (
        "MKT1",
        "Marketing fondamental",
        "marketing",
        "cours",
        "Marché, segmentation, positionnement, mix marketing.",
    ),
    (
        "MKTD",
        "Marketing digital",
        "marketing",
        "tp",
        "Référencement, réseaux sociaux, publicité en ligne, mesure d'audience.",
    ),
    (
        "ETMKT",
        "Études de marché",
        "marketing",
        "tp",
        "Questionnaires, échantillonnage, analyse de données d'enquête.",
    ),
    (
        "CRM",
        "Gestion de la relation client",
        "marketing",
        "tp",
        "Fidélisation, outils CRM, expérience client.",
    ),
    (
        "FIN1",
        "Finance d'entreprise",
        "finance",
        "cours",
        "Analyse financière, choix d'investissement, financement.",
    ),
    (
        "FIN2",
        "Marchés financiers",
        "finance",
        "cours",
        "Actions, obligations, évaluation, gestion de portefeuille.",
    ),
    ("FISCA", "Fiscalité", "finance", "cours", "Impôts directs et indirects, déclarations."),
    (
        "CTRL",
        "Contrôle de gestion",
        "gestion",
        "cours",
        "Coûts, budgets, tableaux de bord, analyse des écarts.",
    ),
    (
        "GRH",
        "Gestion des ressources humaines",
        "gestion",
        "cours",
        "Recrutement, formation, rémunération, droit du travail.",
    ),
    (
        "DROIT",
        "Droit des affaires",
        "droit",
        "cours",
        "Contrats, sociétés commerciales, droit de la consommation.",
    ),
    (
        "INFOG",
        "Informatique de gestion",
        "informatique",
        "tp",
        "Tableur avancé, bases de données simples, outils collaboratifs.",
    ),
    (
        "SCM",
        "Logistique et chaîne d'approvisionnement",
        "gestion",
        "cours",
        "Approvisionnement, stocks, transport, entreposage.",
    ),
    (
        "COMINT",
        "Commerce international",
        "commerce",
        "cours",
        "Incoterms, opérations de change, procédures douanières.",
    ),
    (
        "ECOM",
        "E-commerce",
        "commerce",
        "tp",
        "Boutique en ligne, paiement électronique, logistique du dernier kilomètre.",
    ),
    (
        "NEGO",
        "Techniques de négociation",
        "commerce",
        "langue",
        "Préparation, conduite et conclusion d'une négociation commerciale.",
    ),
    ("ANGB1", "Anglais des affaires 1", "langues", "langue", "Anglais des affaires, niveau B1."),
    ("ANGB2", "Anglais des affaires 2", "langues", "langue", "Anglais des affaires, niveau B2."),
    (
        "COMB",
        "Communication d'entreprise",
        "langues",
        "langue",
        "Communication écrite et orale en entreprise.",
    ),
    (
        "ENTRB",
        "Entrepreneuriat",
        "transversal",
        "cours",
        "Création d'entreprise, plan d'affaires, financement.",
    ),
    (
        "MGTSTRAT",
        "Management stratégique",
        "management",
        "cours",
        "Diagnostic stratégique, choix stratégiques, mise en œuvre.",
    ),
    (
        "TRANSF",
        "Transformation digitale",
        "management",
        "tp",
        "Stratégie numérique, conduite du changement, nouveaux modèles d'affaires.",
    ),
    (
        "LEAD",
        "Leadership et management d'équipe",
        "management",
        "langue",
        "Styles de leadership, motivation, gestion des conflits.",
    ),
    (
        "DATAB",
        "Analyse de données pour la décision",
        "informatique",
        "tp",
        "Indicateurs, tableaux de bord, initiation à l'analyse prédictive.",
    ),
    (
        "GPROJ",
        "Gestion de projet",
        "management",
        "cours",
        "Cadrage, planification, suivi des coûts et des risques.",
    ),
    ("STAGEB", "Stage d'initiation", "projet", "projet", "Stage d'un mois en entreprise, rapport."),
    (
        "PFEB",
        "Projet de fin d'études",
        "projet",
        "projet",
        "Stage de fin d'études de quatre mois, rapport et soutenance.",
    ),
]

SUBJECTS: dict[str, list[tuple[str, str, str, str, str]]] = {
    "IIT": _IIT_SUBJECTS,
    "ISB": _ISB_SUBJECTS,
}


def hours_for(kind: str, ects: float) -> tuple[float, float, float]:
    """Répartition indicative (CM, TD, TP) d'une matière : environ 10,5 h encadrées par ECTS."""
    total = round(ects * 10.5)
    if kind == "cours":
        cm = round(total * 0.55)
        return float(cm), float(total - cm), 0.0
    if kind == "tp":
        cm = round(total * 0.4)
        td = round(total * 0.2)
        return float(cm), float(td), float(total - cm - td)
    if kind == "langue":
        return 0.0, float(total), 0.0
    # projet / stage : encadrement compté en TP, volume réduit
    return 0.0, 0.0, float(round(ects * 2))


# ================================================================================================
# Cursus (maquettes) : (matière, semestre, UE, coefficient, ECTS[, option])
# ================================================================================================

_UE = {
    "UEF": "Unité fondamentale",
    "UEM": "Unité méthodologique",
    "UET": "Unité transversale",
    "UEO": "Unité optionnelle",
    "UEP": "Projet et stage",
}


def _sem(sem: int, *rows: tuple) -> list[tuple]:
    """Ajoute le semestre à des lignes (matière, UE, coef, ECTS[, option])."""
    out = []
    for row in rows:
        code, ue, coef, ects, *rest = row
        out.append((code, sem, f"{ue}{sem}", _UE[ue], coef, ects, bool(rest and rest[0])))
    return out


CURRICULA: list[dict] = [
    {
        "programme": "LIC-INFO",
        "speciality": "GL",
        "version_label": "v2026",
        "academic_year": "2026-2027",
        "total_ects": 180,
        "notes_fr": "Maquette complète de la Licence informatique, parcours Génie logiciel.",
        "status": "published",
        "valid_from": "2026-09-01",
        "valid_to": None,
        "subjects": [
            *_sem(
                1,
                ("ANA1", "UEF", 2, 6),
                ("ALG1", "UEF", 2, 5),
                ("ALGO1", "UEF", 3, 7),
                ("PROGC", "UEF", 2.5, 6),
                ("ARCHI", "UEM", 1.5, 3),
                ("ANG1", "UET", 1, 3),
            ),
            *_sem(
                2,
                ("ANA2", "UEF", 2, 5),
                ("ALG2", "UEF", 1.5, 4),
                ("ALGO2", "UEF", 3, 7),
                ("POO", "UEF", 2.5, 6),
                ("SYSEXP", "UEM", 2, 5),
                ("FR", "UET", 1, 3),
            ),
            *_sem(
                3,
                ("PROBA", "UEF", 2, 5),
                ("MDISC", "UEF", 1.5, 4),
                ("BD1", "UEF", 2.5, 6),
                ("RES1", "UEF", 2.5, 6),
                ("WEB", "UEM", 2.5, 6),
                ("ANG2", "UET", 1, 3),
            ),
            *_sem(
                4,
                ("GL1", "UEF", 2.5, 6),
                ("BD2", "UEF", 2, 5),
                ("AGILE", "UEF", 2, 5),
                ("MOB", "UEM", 2, 5),
                ("SECU", "UEM", 2, 5),
                ("ENTR", "UET", 1, 2),
                ("STAGE-INIT", "UEP", 1, 2),
            ),
            *_sem(
                5,
                ("IA1", "UEF", 2.5, 6),
                ("CLOUD", "UEF", 2.5, 6),
                ("ARCHLOG", "UEF", 2.5, 6),
                ("PROJ-INT", "UEP", 2.5, 6),
                ("COMPIL", "UEM", 1.5, 3),
                ("ANG3", "UET", 1, 3),
            ),
            *_sem(6, ("PFE-LIC", "UEP", 10, 30)),
        ],
        "prerequisites": [
            ("ANA2", "ANA1", None),
            ("ALG2", "ALG1", None),
            ("ALGO2", "ALGO1", None),
            ("POO", "PROGC", None),
            ("BD2", "BD1", None),
            ("AGILE", "POO", None),
            ("MOB", "POO", None),
            ("SECU", "RES1", None),
            ("IA1", "PROBA", None),
            ("CLOUD", "SYSEXP", None),
            ("ARCHLOG", "WEB", None),
            ("PFE-LIC", None, "Avoir validé au moins 120 crédits des semestres 1 à 4."),
        ],
    },
    {
        # Version expirée : publiée, remplacée le 01/09/2026 (valid_to passé).
        "programme": "LIC-INFO",
        "speciality": "GL",
        "version_label": "v2022",
        "academic_year": "2022-2023",
        "total_ects": 180,
        "notes_fr": "Ancienne maquette (extrait de la 1re année), remplacée par la v2026.",
        "status": "expired",
        "valid_from": "2022-09-01",
        "valid_to": "2026-09-01",
        "subjects": [
            *_sem(
                1,
                ("ANA1", "UEF", 2, 6),
                ("ALG1", "UEF", 2, 6),
                ("ALGO1", "UEF", 3, 8),
                ("PROGC", "UEF", 2, 5),
                ("ANG1", "UET", 1, 5),
            ),
            *_sem(
                2,
                ("ANA2", "UEF", 2, 6),
                ("ALGO2", "UEF", 3, 8),
                ("POO", "UEF", 2, 6),
                ("ARCHI", "UEM", 2, 5),
                ("FR", "UET", 1, 5),
            ),
        ],
        "prerequisites": [("ALGO2", "ALGO1", None)],
    },
    {
        "programme": "LIC-ELEC",
        "speciality": None,
        "version_label": "v2026",
        "academic_year": "2026-2027",
        "total_ects": 180,
        "notes_fr": "Extrait : 1re année (tronc commun).",
        "status": "published",
        "valid_from": "2026-09-01",
        "valid_to": None,
        "subjects": [
            *_sem(
                1,
                ("ANA1", "UEF", 2, 6),
                ("ALG1", "UEF", 2, 5),
                ("ELN1", "UEF", 3, 7),
                ("ELT1", "UEF", 2.5, 6),
                ("PROGC", "UEM", 1.5, 3),
                ("ANG1", "UET", 1, 3),
            ),
            *_sem(
                2,
                ("ANA2", "UEF", 2, 5),
                ("LOGIQ", "UEF", 2.5, 6),
                ("ELEC", "UEF", 2.5, 6),
                ("MICROC", "UEM", 2, 5),
                ("PROBA", "UEM", 2, 5),
                ("FR", "UET", 1, 3),
            ),
        ],
        "prerequisites": [("ANA2", "ANA1", None), ("MICROC", "PROGC", None)],
    },
    {
        "programme": "LIC-MECA",
        "speciality": None,
        "version_label": "v2026",
        "academic_year": "2026-2027",
        "total_ects": 180,
        "notes_fr": "Extrait : 1re année.",
        "status": "published",
        "valid_from": "2026-09-01",
        "valid_to": None,
        "subjects": [
            *_sem(
                1,
                ("ANA1", "UEF", 2, 6),
                ("ALG1", "UEF", 2, 5),
                ("MECAG", "UEF", 3, 7),
                ("CAO", "UEF", 2.5, 6),
                ("MATER", "UEM", 1.5, 3),
                ("ANG1", "UET", 1, 3),
            ),
            *_sem(
                2,
                ("ANA2", "UEF", 2, 5),
                ("RDM", "UEF", 3, 7),
                ("THERMO", "UEF", 2, 5),
                ("PYTHON", "UEM", 2, 5),
                ("ELT1", "UEM", 2, 5),
                ("FR", "UET", 1, 3),
            ),
        ],
        "prerequisites": [("RDM", "MECAG", None), ("ANA2", "ANA1", None)],
    },
    {
        "programme": "LIC-GC",
        "speciality": None,
        "version_label": "v2026",
        "academic_year": "2026-2027",
        "total_ects": 180,
        "notes_fr": "Extrait : 1re année.",
        "status": "published",
        "valid_from": "2026-09-01",
        "valid_to": None,
        "subjects": [
            *_sem(
                1,
                ("ANA1", "UEF", 2, 6),
                ("ALG1", "UEF", 2, 5),
                ("MECAG", "UEF", 2.5, 6),
                ("TOPO", "UEF", 2.5, 6),
                ("MATCON", "UEM", 2, 4),
                ("ANG1", "UET", 1, 3),
            ),
            *_sem(
                2,
                ("ANA2", "UEF", 2, 5),
                ("RDM", "UEF", 3, 7),
                ("CAO", "UEF", 2.5, 6),
                ("PROBA", "UEM", 1.5, 4),
                ("PYTHON", "UEM", 2, 5),
                ("FR", "UET", 1, 3),
            ),
        ],
        "prerequisites": [("RDM", "MECAG", None)],
    },
    {
        "programme": "PREPA-MP",
        "speciality": None,
        "version_label": "v2024",
        "academic_year": "2024-2025",
        "total_ects": 120,
        "notes_fr": "Maquette complète des deux années de prépa MP.",
        "status": "published",
        "valid_from": "2024-09-01",
        "valid_to": None,
        "subjects": [
            *_sem(
                1,
                ("ANA-P1", "UEF", 3, 8),
                ("ALG-P1", "UEF", 2.5, 6),
                ("MECA", "UEF", 2.5, 6),
                ("ELEC", "UEF", 1.5, 4),
                ("PYTHON", "UEM", 1, 3),
                ("ANG1", "UET", 1, 3),
            ),
            *_sem(
                2,
                ("ANA-P2", "UEF", 3, 8),
                ("ALG-P2", "UEF", 2.5, 6),
                ("THERMO", "UEF", 2, 5),
                ("OPTQ", "UEF", 1.5, 4),
                ("CHIM", "UEM", 1.5, 4),
                ("FR", "UET", 1, 3),
            ),
            *_sem(
                3,
                ("ANA-P3", "UEF", 3, 8),
                ("ALG-P3", "UEF", 2.5, 6),
                ("MECA2", "UEF", 2.5, 6),
                ("ELEC2", "UEF", 1.5, 4),
                ("PYTHON2", "UEM", 1, 3),
                ("ANG2", "UET", 1, 3),
            ),
            *_sem(
                4,
                ("ANA-P4", "UEF", 3, 8),
                ("PROBA", "UEF", 2, 5),
                ("SI", "UEF", 2.5, 6),
                ("CHIM2", "UEM", 1.5, 4),
                ("PROJ-PREPA", "UEP", 1.5, 4),
                ("ANG3", "UET", 1, 3),
            ),
        ],
        "prerequisites": [
            ("ANA-P2", "ANA-P1", None),
            ("ANA-P3", "ANA-P2", None),
            ("ANA-P4", "ANA-P3", None),
            ("ALG-P2", "ALG-P1", None),
            ("ALG-P3", "ALG-P2", None),
            ("MECA2", "MECA", None),
            ("ELEC2", "ELEC", None),
            ("PYTHON2", "PYTHON", None),
        ],
    },
    {
        "programme": "PREPA-PT",
        "speciality": None,
        "version_label": "v2024",
        "academic_year": "2024-2025",
        "total_ects": 120,
        "notes_fr": "Extrait : 1re année de prépa PT.",
        "status": "published",
        "valid_from": "2024-09-01",
        "valid_to": None,
        "subjects": [
            *_sem(
                1,
                ("ANA-P1", "UEF", 2.5, 7),
                ("ALG-P1", "UEF", 2, 5),
                ("MECA", "UEF", 2.5, 6),
                ("SI", "UEF", 2.5, 6),
                ("TECHDES", "UEM", 1, 3),
                ("ANG1", "UET", 1, 3),
            ),
            *_sem(
                2,
                ("ANA-P2", "UEF", 2.5, 7),
                ("ELEC", "UEF", 2.5, 6),
                ("THERMO", "UEF", 2, 5),
                ("PYTHON", "UEM", 1.5, 4),
                ("CHIM", "UEM", 2, 5),
                ("FR", "UET", 1, 3),
            ),
        ],
        "prerequisites": [("ANA-P2", "ANA-P1", None)],
    },
    {
        "programme": "ING",
        "speciality": "GINFO",
        "version_label": "v2026",
        "academic_year": "2026-2027",
        "total_ects": 180,
        "notes_fr": (
            "Maquette complète du génie informatique. Au semestre 3, l'étudiant choisit une "
            "option (NLP ou Vision) : une seule est comptée dans les 30 crédits."
        ),
        "status": "published",
        "valid_from": "2026-09-01",
        "valid_to": None,
        "subjects": [
            *_sem(
                1,
                ("ANUM", "UEF", 2, 5),
                ("RO", "UEF", 2, 5),
                ("COMPIL", "UEF", 2, 5),
                ("ML", "UEF", 2.5, 6),
                ("ARCHLOG", "UEF", 2.5, 6),
                ("ANG3", "UET", 1, 3),
            ),
            *_sem(
                2,
                ("DL", "UEF", 2.5, 6),
                ("BIGDATA", "UEF", 2.5, 6),
                ("SYSDIST", "UEF", 2, 5),
                ("SECU", "UEM", 2, 5),
                ("CLOUD", "UEM", 2, 5),
                ("ENTR", "UET", 1, 3),
            ),
            *_sem(
                3,
                ("NLP", "UEO", 2, 5, True),
                ("VISION", "UEO", 2, 5, True),
                ("MOB", "UEF", 2, 5),
                ("AGILE", "UEF", 2, 5),
                ("BD2", "UEF", 2, 5),
                ("PROJ-INT", "UEP", 2.5, 6),
                ("FR", "UET", 1.5, 4),
            ),
            *_sem(
                4,
                ("IOT", "UEF", 2.5, 6),
                ("MLOPS", "UEF", 2.5, 6),
                ("GESTPROJ", "UEM", 2, 5),
                ("STAGE-ING", "UEP", 4, 10),
                ("ANG2", "UET", 1, 3),
            ),
            *_sem(
                5,
                ("RECH", "UEM", 2.5, 6),
                ("IAETH", "UEM", 1.5, 4),
                ("PROJ-ING", "UEP", 4, 10),
                ("DATAVIZ", "UEF", 2, 5),
                ("SOFT", "UET", 2, 5),
            ),
            *_sem(6, ("PFE-ING", "UEP", 10, 30)),
        ],
        "prerequisites": [
            ("DL", "ML", None),
            ("NLP", "DL", None),
            ("VISION", "DL", None),
            ("MLOPS", "ML", None),
            ("MLOPS", "CLOUD", None),
            ("ML", None, "Probabilités, statistiques et programmation Python (niveau Licence)."),
            ("PFE-ING", None, "Avoir validé les semestres 1 à 5 et le stage d'ingénieur."),
        ],
    },
    {
        "programme": "ING",
        "speciality": "GELEC",
        "version_label": "v2026",
        "academic_year": "2026-2027",
        "total_ects": 180,
        "notes_fr": "Extrait : 1re année du génie électrique.",
        "status": "published",
        "valid_from": "2026-09-01",
        "valid_to": None,
        "subjects": [
            *_sem(
                1,
                ("AUTO", "UEF", 2.5, 6),
                ("SIGNAL", "UEF", 2.5, 6),
                ("ANUM", "UEF", 2, 5),
                ("MICROC", "UEF", 2.5, 6),
                ("ELN2", "UEM", 1.5, 4),
                ("ANG3", "UET", 1, 3),
            ),
            *_sem(
                2,
                ("CMD", "UEF", 2.5, 6),
                ("IOT", "UEF", 2.5, 6),
                ("RESIND", "UEF", 2, 5),
                ("ENERG", "UEM", 2, 5),
                ("RO", "UEM", 2, 5),
                ("ENTR", "UET", 1, 3),
            ),
        ],
        "prerequisites": [("CMD", "AUTO", None), ("IOT", "MICROC", None)],
    },
    {
        "programme": "LIC-GEST",
        "speciality": None,
        "version_label": "v2025",
        "academic_year": "2025-2026",
        "total_ects": 180,
        "notes_fr": "Maquette complète ; spécialisation Finance ou Marketing à partir du S4.",
        "status": "published",
        "valid_from": "2025-09-01",
        "valid_to": None,
        "subjects": [
            *_sem(
                1,
                ("PGE", "UEF", 2.5, 6),
                ("MICRO", "UEF", 2.5, 6),
                ("CPT1", "UEF", 2.5, 6),
                ("MATHG", "UEM", 2, 5),
                ("ANGB1", "UET", 1.5, 4),
                ("INFOG", "UET", 1, 3),
            ),
            *_sem(
                2,
                ("MACRO", "UEF", 2.5, 6),
                ("CPT2", "UEF", 2.5, 6),
                ("STATG", "UEM", 2, 5),
                ("MKT1", "UEF", 2.5, 6),
                ("DROIT", "UEM", 1.5, 4),
                ("COMB", "UET", 1, 3),
            ),
            *_sem(
                3,
                ("FIN1", "UEF", 2.5, 6),
                ("CTRL", "UEF", 2.5, 6),
                ("GRH", "UEF", 2, 5),
                ("SCM", "UEM", 2, 5),
                ("ANGB2", "UET", 1.5, 4),
                ("ENTRB", "UET", 1.5, 4),
            ),
            *_sem(
                4,
                ("FIN2", "UEF", 2.5, 6),
                ("MKTD", "UEF", 2.5, 6),
                ("FISCA", "UEF", 2, 5),
                ("ETMKT", "UEM", 2, 5),
                ("CRM", "UEM", 2, 5),
                ("STAGEB", "UEP", 1, 3),
            ),
            *_sem(
                5,
                ("MGTSTRAT", "UEF", 2.5, 6),
                ("DATAB", "UEF", 2.5, 6),
                ("GPROJ", "UEM", 2.5, 6),
                ("COMINT", "UEM", 2.5, 6),
                ("NEGO", "UET", 2.5, 6),
            ),
            *_sem(6, ("PFEB", "UEP", 10, 30)),
        ],
        "prerequisites": [
            ("CPT2", "CPT1", None),
            ("MACRO", "MICRO", None),
            ("FIN1", "CPT2", None),
            ("CTRL", "CPT2", None),
            ("FIN2", "FIN1", None),
            ("MKTD", "MKT1", None),
            ("ETMKT", "STATG", None),
        ],
    },
    {
        "programme": "LIC-COMM",
        "speciality": None,
        "version_label": "v2025",
        "academic_year": "2025-2026",
        "total_ects": 180,
        "notes_fr": "Extrait : 1re année.",
        "status": "published",
        "valid_from": "2025-09-01",
        "valid_to": None,
        "subjects": [
            *_sem(
                1,
                ("PGE", "UEF", 2.5, 6),
                ("MICRO", "UEF", 2.5, 6),
                ("COMINT", "UEF", 2.5, 6),
                ("MATHG", "UEM", 1.5, 4),
                ("ANGB1", "UET", 2, 5),
                ("INFOG", "UET", 1, 3),
            ),
            *_sem(
                2,
                ("MACRO", "UEF", 2.5, 6),
                ("MKT1", "UEF", 2.5, 6),
                ("ECOM", "UEF", 2.5, 6),
                ("STATG", "UEM", 1.5, 4),
                ("ANGB2", "UET", 2, 5),
                ("NEGO", "UET", 1, 3),
            ),
        ],
        "prerequisites": [("ANGB2", "ANGB1", None), ("ECOM", None, "Bases du tableur.")],
    },
    {
        "programme": "MP-MGT",
        "speciality": None,
        "version_label": "v2025",
        "academic_year": "2025-2026",
        "total_ects": 120,
        "notes_fr": "Extrait : 1re année du master.",
        "status": "published",
        "valid_from": "2025-09-01",
        "valid_to": None,
        "subjects": [
            *_sem(
                1,
                ("MGTSTRAT", "UEF", 3, 7),
                ("TRANSF", "UEF", 3, 7),
                ("LEAD", "UEM", 2, 5),
                ("DATAB", "UEF", 2.5, 6),
                ("GPROJ", "UEM", 2, 5),
            ),
            *_sem(
                2,
                ("MKTD", "UEF", 2.5, 6),
                ("FIN2", "UEF", 2.5, 6),
                ("CRM", "UEM", 2, 5),
                ("ENTRB", "UEM", 2, 5),
                ("ETMKT", "UEP", 3, 8),
            ),
        ],
        "prerequisites": [
            ("DATAB", None, "Statistiques descriptives et tableur (niveau Licence)."),
        ],
    },
]

# ================================================================================================
# Conditions d'admission (par rentrée, D-I)
# ================================================================================================

_SCI = ["mathematiques", "sciences_experimentales", "sciences_techniques", "sciences_informatique"]


def _bac_condition(
    programme: str,
    sections: list[str],
    min_average: str,
    requirements: list[tuple[str, str, str]],
    summary: str,
    *,
    test: bool = False,
    interview: bool = False,
    places: int | None = None,
) -> dict:
    """Condition d'entrée en 1re année pour un nouveau bachelier (gabarit par formation)."""
    return {
        "programme": programme,
        "speciality": None,
        "entry_level": 1,
        "applicant_category": "new_bachelor",
        "required_diploma": "baccalaureate",
        "accepted_bac_sections": sections,
        "min_validated_years": 0,
        "min_average": min_average,
        "average_basis": "bac_average",
        "requires_application_file": True,
        "requires_test": test,
        "requires_interview": interview,
        "max_places": places,
        "summary_fr": summary,
        "requirements": requirements,
    }


_MATHS = ("mathematiques", "Mathématiques")
_PHYS = ("physique", "Physique")
_ANG = ("anglais", "Anglais")

_ADMISSION_TEMPLATES: list[dict] = [
    _bac_condition(
        "LIC-INFO",
        _SCI,
        "10.00",
        [(*_MATHS, "10.00")],
        "Bac Mathématiques, Sciences expérimentales, Techniques ou Informatique ; moyenne du bac "
        "≥ 10 et note de mathématiques ≥ 10 ; dossier et QCM de positionnement.",
        test=True,
        places=90,
    ),
    _bac_condition(
        "LIC-ELEC",
        ["mathematiques", "sciences_experimentales", "sciences_techniques"],
        "10.00",
        [(*_PHYS, "10.00")],
        "Bac Mathématiques, Sciences expérimentales ou Techniques ; moyenne ≥ 10 et note de "
        "physique ≥ 10 ; étude du dossier.",
        places=40,
    ),
    _bac_condition(
        "LIC-MECA",
        ["mathematiques", "sciences_techniques"],
        "10.00",
        [(*_MATHS, "9.00")],
        "Bac Mathématiques ou Techniques ; moyenne ≥ 10 et note de mathématiques ≥ 9.",
        places=35,
    ),
    _bac_condition(
        "LIC-GC",
        ["mathematiques", "sciences_experimentales", "sciences_techniques"],
        "10.00",
        [],
        "Bac Mathématiques, Sciences expérimentales ou Techniques ; moyenne ≥ 10.",
        places=35,
    ),
    _bac_condition(
        "PREPA-MP",
        ["mathematiques", "sciences_techniques", "sciences_informatique"],
        "12.00",
        [(*_MATHS, "12.00"), (*_PHYS, "11.00")],
        "Bac Mathématiques, Techniques ou Informatique ; moyenne ≥ 12, mathématiques ≥ 12, "
        "physique ≥ 11 ; QCM et entretien de motivation.",
        test=True,
        interview=True,
        places=60,
    ),
    _bac_condition(
        "PREPA-PT",
        ["sciences_techniques", "mathematiques"],
        "11.00",
        [(*_PHYS, "10.00")],
        "Bac Techniques ou Mathématiques ; moyenne ≥ 11 et physique ≥ 10 ; entretien.",
        interview=True,
        places=40,
    ),
    {
        "programme": "ING",
        "speciality": None,
        "entry_level": 1,
        "applicant_category": "higher_education_graduate",
        "required_diploma": "licence",
        "accepted_bac_sections": None,
        "min_validated_years": 3,
        "min_average": "12.00",
        "average_basis": "last_year_average",
        "requires_application_file": True,
        "requires_test": False,
        "requires_interview": True,
        "max_places": 40,
        "summary_fr": (
            "Titulaires d'une Licence (3 ans validés) dans le domaine de la spécialité ; moyenne "
            "de dernière année ≥ 12 ; dossier et entretien. Les élèves de la prépa intégrée IIT "
            "passent par la passerelle automatique."
        ),
        "requirements": [],
    },
    {
        "programme": "ING",
        "speciality": None,
        "entry_level": 2,
        "applicant_category": "transfer_student",
        "required_diploma": "other_higher_education",
        "accepted_bac_sections": None,
        "min_validated_years": 3,
        "min_average": "12.00",
        "average_basis": "last_year_average",
        "requires_application_file": True,
        "requires_test": True,
        "requires_interview": True,
        "max_places": 10,
        "summary_fr": (
            "Transfert en 2e année du cycle ingénieur après une 1re année d'ingénieur validée "
            "ailleurs ; moyenne ≥ 12 ; demande d'équivalence, test et entretien."
        ),
        "requirements": [],
    },
    {
        "programme": "LIC-INFO",
        "speciality": None,
        "entry_level": 2,
        "applicant_category": "transfer_student",
        "required_diploma": "other_higher_education",
        "accepted_bac_sections": None,
        "min_validated_years": 1,
        "min_average": "10.00",
        "average_basis": "last_year_average",
        "requires_application_file": True,
        "requires_test": False,
        "requires_interview": True,
        "max_places": 15,
        "summary_fr": (
            "Réorientation en 2e année après au moins une année d'études supérieures validée ; "
            "moyenne ≥ 10 ; demande d'équivalence des matières et entretien."
        ),
        "requirements": [],
    },
    _bac_condition(
        "LIC-GEST",
        [
            "economie_gestion",
            "mathematiques",
            "sciences_experimentales",
            "sciences_techniques",
            "sciences_informatique",
            "lettres",
        ],
        "10.00",
        [],
        "Toutes séries sauf Sport ; moyenne du bac ≥ 10 ; étude du dossier.",
        places=80,
    ),
    _bac_condition(
        "LIC-COMM",
        ["economie_gestion", "mathematiques", "sciences_experimentales", "lettres"],
        "10.00",
        [(*_ANG, "10.00")],
        "Bac Économie et gestion, Mathématiques, Sciences expérimentales ou Lettres ; moyenne "
        "≥ 10 et anglais ≥ 10 ; entretien en anglais.",
        interview=True,
        places=40,
    ),
    {
        "programme": "MP-MGT",
        "speciality": None,
        "entry_level": 1,
        "applicant_category": "higher_education_graduate",
        "required_diploma": "licence",
        "accepted_bac_sections": None,
        "min_validated_years": 3,
        "min_average": "11.00",
        "average_basis": "last_year_average",
        "requires_application_file": True,
        "requires_test": False,
        "requires_interview": True,
        "max_places": 35,
        "summary_fr": (
            "Titulaires d'une Licence (gestion, commerce, informatique ou ingénierie) ; moyenne "
            "de dernière année ≥ 11 ; dossier et entretien."
        ),
        "requirements": [],
    },
]


def _admission_conditions() -> list[dict]:
    """Développe les gabarits sur deux rentrées + cas de démo (brouillon, relecture, expiré)."""
    out: list[dict] = []
    for tpl in _ADMISSION_TEMPLATES:
        prog = tpl["programme"]
        # Rentrée 2026-2027 : publiée depuis la campagne de novembre 2025.
        out.append(
            {
                **tpl,
                "academic_year": "2026-2027",
                "status": "published",
                "valid_from": "2025-11-01",
                "valid_to": None,
            }
        )
        # Rentrée 2027-2028 : campagne ouverte depuis le 01/10/2026.
        status_2027 = {"LIC-GC": "pending_review", "LIC-MECA": "draft"}.get(prog, "published")
        nxt = {
            **tpl,
            "academic_year": "2027-2028",
            "status": status_2027,
            "valid_from": "2026-10-01",
            "valid_to": None,
        }
        if prog == "LIC-INFO" and tpl["applicant_category"] == "new_bachelor":
            # Évolution d'une rentrée à l'autre : seuil de moyenne relevé à 10,5.
            nxt["min_average"] = "10.50"
            nxt["summary_fr"] = tpl["summary_fr"].replace("bac ≥ 10 ", "bac ≥ 10,5 ")
        out.append(nxt)
    # Version expirée : conditions 2025-2026 de LIC-INFO (valides jusqu'au 01/09/2026).
    lic = _ADMISSION_TEMPLATES[0]
    out.append(
        {
            **lic,
            "academic_year": "2025-2026",
            "status": "expired",
            "valid_from": "2024-11-01",
            "valid_to": "2026-09-01",
            "summary_fr": "Conditions de la rentrée 2025-2026 (campagne close).",
        }
    )
    return out


ADMISSION_CONDITIONS: list[dict] = _admission_conditions()

# ================================================================================================
# Frais (une grille officielle par année universitaire, D-A)
# ================================================================================================

_OTHER_LABEL = "Assurance, carte d'étudiant et accès aux plateformes numériques"

# (formation, spécialité, catégorie, inscription, scolarité, autres frais) pour 2026-2027
_FEES_2026: list[tuple[str, str | None, str, str, str, str]] = [
    ("LIC-INFO", None, "tunisian", "300.000", "6200.000", "150.000"),
    ("LIC-ELEC", None, "tunisian", "300.000", "5900.000", "150.000"),
    ("LIC-MECA", None, "tunisian", "300.000", "5900.000", "150.000"),
    ("LIC-GC", None, "tunisian", "300.000", "5800.000", "150.000"),
    ("PREPA-MP", None, "tunisian", "300.000", "6300.000", "150.000"),
    ("PREPA-PT", None, "tunisian", "300.000", "6300.000", "150.000"),
    ("ING", None, "tunisian", "350.000", "7800.000", "200.000"),
    # Précédence (SA-12 règle 6) : la grille de la spécialité l'emporte sur celle de la formation.
    ("ING", "GINFO", "tunisian", "350.000", "8200.000", "200.000"),
    ("ING", None, "foreign", "450.000", "9600.000", "250.000"),
    ("LIC-GEST", None, "tunisian", "250.000", "5200.000", "120.000"),
    ("LIC-COMM", None, "tunisian", "250.000", "5400.000", "120.000"),
    ("MP-MGT", None, "tunisian", "300.000", "6800.000", "150.000"),
]


def _scaled(amount: str, rate: str) -> str:
    """Montant revalorisé et arrondi à la dizaine de dinars (chaîne décimale)."""
    from decimal import ROUND_HALF_UP, Decimal

    value = (Decimal(amount) * Decimal(rate) / 10).quantize(Decimal("1"), ROUND_HALF_UP) * 10
    return f"{value:.3f}"


def _fee(
    prog, spec, cat, reg, tuition, other, *, year, status, valid_from, valid_to=None, notes=None
) -> dict:
    return {
        "programme": prog,
        "speciality": spec,
        "study_year": None,
        "student_category": cat,
        "academic_year": year,
        "registration_fee": reg,
        "annual_tuition_fee": tuition,
        "other_fees": other,
        "other_fees_label_fr": _OTHER_LABEL if other != "0.000" else None,
        "notes_fr": notes,
        "status": status,
        "valid_from": valid_from,
        "valid_to": valid_to,
    }


def _fee_schedules() -> list[dict]:
    out: list[dict] = []
    for prog, spec, cat, reg, tuition, other in _FEES_2026:
        # 2026-2027 : publiée.
        out.append(
            _fee(
                prog,
                spec,
                cat,
                reg,
                tuition,
                other,
                year="2026-2027",
                status="published",
                valid_from="2026-03-01",
            )
        )
        # 2027-2028 : soumise, en attente de la relecture à quatre yeux (invisible pour l'agent),
        # sauf la grille GINFO restée en brouillon.
        status = "draft" if spec == "GINFO" else "pending_review"
        out.append(
            _fee(
                prog,
                spec,
                cat,
                reg,
                _scaled(tuition, "1.04"),
                other,
                year="2027-2028",
                status=status,
                valid_from="2026-12-01",
                notes="Projet de grille 2027-2028 (revalorisation de 4 %).",
            )
        )
    # 2025-2026 : publiées puis expirées le 01/09/2026 (démo « version expirée invisible »).
    for prog, reg, tuition, other in (
        ("LIC-INFO", "280.000", "5950.000", "150.000"),
        ("ING", "330.000", "7500.000", "200.000"),
    ):
        out.append(
            _fee(
                prog,
                None,
                "tunisian",
                reg,
                tuition,
                other,
                year="2025-2026",
                status="expired",
                valid_from="2025-03-01",
                valid_to="2026-09-01",
            )
        )
    # 2024-2025 : archivée.
    out.append(
        _fee(
            "LIC-INFO",
            None,
            "tunisian",
            "280.000",
            "5700.000",
            "0.000",
            year="2024-2025",
            status="archived",
            valid_from="2024-03-01",
            valid_to="2025-09-01",
        )
    )
    return out


FEE_SCHEDULES: list[dict] = _fee_schedules()

#: Plans de paiement créés pour chaque grille : (code, libellé, nb de tranches, remise %, défaut).
PAYMENT_PLANS: list[tuple[str, str, int, str, bool]] = [
    ("TRANCHES-3", "Paiement en 3 tranches", 3, "0.00", True),
    ("COMPTANT", "Paiement comptant (remise de 3 %)", 1, "3.00", False),
]

# ================================================================================================
# Passerelles (Path Explorer)
# ================================================================================================

BRIDGES: list[dict] = [
    {
        "source": ("PREPA-MP", None),
        "years": 2,
        "target": ("ING", None),
        "level": 1,
        "access_mode": "automatic",
        "status": "published",
        "valid_from": "2024-09-01",
        "summary": "Passage automatique en 1re année du cycle ingénieur si les deux années de "
        "prépa sont validées ; choix de la spécialité selon le classement.",
    },
    {
        "source": ("PREPA-PT", None),
        "years": 2,
        "target": ("ING", None),
        "level": 1,
        "access_mode": "automatic",
        "status": "published",
        "valid_from": "2024-09-01",
        "summary": "Passage automatique en 1re année du cycle ingénieur (spécialités électrique, "
        "mécanique, civil ou industriel) si les deux années sont validées.",
    },
    {
        "source": ("PREPA-MP", None),
        "years": 1,
        "target": ("LIC-INFO", None),
        "level": 2,
        "access_mode": "on_application",
        "status": "published",
        "valid_from": "2024-09-01",
        "summary": "Réorientation en 2e année de Licence informatique après une année de prépa "
        "validée, sur dossier.",
    },
    {
        "source": ("LIC-INFO", None),
        "years": 3,
        "target": ("ING", "GINFO"),
        "level": 1,
        "access_mode": "on_application",
        "status": "published",
        "valid_from": "2025-09-01",
        "summary": "Licence informatique validée, moyenne de 3e année ≥ 12 ; dossier et entretien.",
    },
    {
        # Ancienne passerelle sans spécialité cible, archivée (remplacée par la précédente).
        "source": ("LIC-INFO", None),
        "years": 3,
        "target": ("ING", None),
        "level": 1,
        "access_mode": "on_application",
        "status": "archived",
        "valid_from": "2020-09-01",
        "valid_to": "2025-09-01",
        "summary": "Ancienne passerelle Licence → cycle ingénieur (toutes spécialités).",
    },
    {
        "source": ("LIC-ELEC", None),
        "years": 3,
        "target": ("ING", "GELEC"),
        "level": 1,
        "access_mode": "on_application",
        "status": "published",
        "valid_from": "2024-09-01",
        "summary": "Licence en génie électrique validée, moyenne de 3e année ≥ 12 ; dossier et "
        "entretien.",
    },
    {
        "source": ("LIC-MECA", None),
        "years": 3,
        "target": ("ING", "GMECA"),
        "level": 1,
        "access_mode": "on_application",
        "status": "published",
        "valid_from": "2024-09-01",
        "summary": "Licence en génie mécanique validée, moyenne de 3e année ≥ 12 ; dossier et "
        "entretien.",
    },
    {
        "source": ("LIC-GC", None),
        "years": 3,
        "target": ("ING", "GCIV"),
        "level": 1,
        "access_mode": "on_application",
        "status": "published",
        "valid_from": "2024-09-01",
        "summary": "Licence en génie civil validée, moyenne de 3e année ≥ 12 ; dossier et "
        "entretien.",
    },
    {
        "source": ("LIC-GEST", None),
        "years": 3,
        "target": ("MP-MGT", None),
        "level": 1,
        "access_mode": "on_application",
        "status": "published",
        "valid_from": "2024-09-01",
        "summary": "Licence en sciences de gestion validée ; dossier et entretien.",
    },
    {
        # En relecture : soumise par le responsable ISB, à publier par la direction.
        "source": ("LIC-COMM", None),
        "years": 3,
        "target": ("MP-MGT", None),
        "level": 1,
        "access_mode": "on_application",
        "status": "pending_review",
        "valid_from": "2026-12-01",
        "summary": "Licence en commerce international validée ; dossier et entretien.",
    },
]
