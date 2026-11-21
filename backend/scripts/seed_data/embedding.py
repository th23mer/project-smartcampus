"""Modèle d'embedding actif (SA-14 : un seul actif, dimension = EMBEDDING_DIM = 1024).

NOM PROVISOIRE : le choix du modèle d'embedding revient à E4 (Waddah, Ossema). `BAAI/bge-m3`
(multilingue, 1024 dimensions, licence MIT) n'est qu'un candidat plausible pour que le schéma RAG
soit utilisable en dev ; la révision `provisoire-sa18` le signale. Modèle pré-entraîné
« sur étagère » : à justifier dans le journal des décisions s'il est retenu.
"""

from __future__ import annotations

EMBEDDING_MODEL: dict = {
    "name": "BAAI/bge-m3",
    "revision": "provisoire-sa18",
    "dimension": 1024,
    "distance": "cosine",
    "max_input_tokens": 8192,
    "is_active": True,
}
