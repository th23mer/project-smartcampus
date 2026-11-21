# `app/config/` — chargeur des fichiers YAML

Les fichiers YAML non secrets sont dans `backend/config/` (ex. `app.yaml`). Ce paquet
fournit `load_yaml_config(name)` (`yaml.safe_load`) et accueillera les schémas Pydantic des
configurations de domaine (modèles, seuils, planification des jobs). Les secrets ne vont
jamais dans un YAML.
