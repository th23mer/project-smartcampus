# `app/api/` — routeurs HTTP

`v1/` contient un module par domaine de SA-5 (`health.py`, `catalogue*.py`…), inclus dans
`v1/router.py` sous le préfixe `/api/v1`. Les routeurs ne contiennent **pas** de logique
métier : ils valident l'entrée (schémas), contrôlent l'accès (`require_roles`) et appellent
un service.
