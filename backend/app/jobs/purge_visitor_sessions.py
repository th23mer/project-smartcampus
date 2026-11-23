"""Tâche de purge des sessions visiteur (SA-25, D-D).

1. sessions `active` dont l'expiration (24 h d'inactivité ou 7 j) est passée → `expired` ;
2. sessions `expired` depuis plus de 30 jours → conversations et messages supprimés,
   statut `purged`.

Lancement (à planifier une fois par heure, par cron ou par le worker de jobs) :

    uv run python -m app.jobs.purge_visitor_sessions
"""

from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.core.db import dispose_engine, get_sessionmaker
from app.services.visitor_sessions import expire_and_purge


async def main() -> None:
    settings = get_settings()
    async with get_sessionmaker()() as session:
        report = await expire_and_purge(session, settings)
    await dispose_engine()
    print(f"Sessions expirées : {report.expired} ; sessions purgées : {report.purged}")


if __name__ == "__main__":
    asyncio.run(main())
