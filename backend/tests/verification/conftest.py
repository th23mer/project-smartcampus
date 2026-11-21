"""Fixtures de la suite de vérification transverse (SA-22).

Réutilise la base réelle et le jeu `World` de `tests/api/conftest.py` (transaction externe
annulée à la fin de chaque test). Lancement (une seule session pytest à la fois sur db-test) :

    set -a; . ../.env; set +a
    flock <scratchpad>/db-test.lock ~/.local/bin/uv run pytest tests/verification
"""

from __future__ import annotations

import pytest

from tests.api.conftest import (  # noqa: F401 (fixtures pytest réexportées)
    api,
    api_migrated,
    api_raw,
    db_conn,
    db_session,
    world,
)

pytestmark = pytest.mark.db
