# `app/models/` — modèles SQLAlchemy (E2, SA-17)

Tables de SA-12 (catalogue), SA-13 (utilisateurs, candidatures) et SA-14 (documents, sync).

- Hériter de `app.core.db.Base` (convention de nommage SA-12 §0 déjà configurée).
- Importer chaque module dans `app/models/__init__.py` (sinon Alembic ne voit pas la table).
- CHECK / EXCLUDE : donner seulement la règle (`name="four_eyes"` → `ck_<table>_four_eyes`).
- Propriétaire après SA-7 : **SA-17**. SA-7 n'a créé que ce squelette.
