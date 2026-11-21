# `app/core/` — socle transverse (SA-7)

| Module | Rôle |
|---|---|
| `config.py` | Réglages (`Settings`) : env > `.env` > `config/app.yaml` > défauts |
| `db.py` | Moteur async, `get_session`, `Base` (convention de nommage SA-12 §0) |
| `errors.py` | Format d'erreur SA-5, `ErrorCode`, `AppError`, gestionnaires globaux |
| `request_id.py` | En-tête `X-Request-ID`, middleware, 500 sans trace |
| `security.py` | `CurrentUser`, `get_current_user`, `require_roles` (auth simulée en dev/test) |
| `pagination.py` | `PageParams`, `Page[T]`, pagination par curseur |
| `logging.py` | Journaux JSON avec `request_id` |
