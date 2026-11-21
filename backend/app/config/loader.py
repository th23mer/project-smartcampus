"""Lecture sûre d'un fichier YAML de `backend/config/`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

#: Dossier `backend/config/` (calculé depuis l'emplacement de ce fichier).
CONFIG_DIR: Path = Path(__file__).resolve().parents[2] / "config"


def load_yaml_config(name: str, *, config_dir: Path | None = None) -> dict[str, Any]:
    """Charge `<config_dir>/<name>.yaml` et renvoie un dictionnaire.

    Utilise `yaml.safe_load` (jamais `yaml.load`). Un fichier absent ou vide donne `{}`.
    Lève `ValueError` si la racine du document n'est pas un dictionnaire.
    """
    path = (config_dir or CONFIG_DIR) / f"{name}.yaml"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} : la racine du YAML doit être un dictionnaire.")
    return data
