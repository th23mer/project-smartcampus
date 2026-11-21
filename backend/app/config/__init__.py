"""Chargement des fichiers de configuration YAML non secrets (`backend/config/*.yaml`).

Les fichiers YAML vivent dans `backend/config/` ; ce paquet fournit le chargeur commun
et, plus tard, les schémas Pydantic des configurations de domaine (modèles, seuils,
planification des jobs…). Les réglages d'exécution (env, URL de base) sont dans
`app.core.config`.
"""

from app.config.loader import CONFIG_DIR, load_yaml_config

__all__ = ["CONFIG_DIR", "load_yaml_config"]
