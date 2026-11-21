"""Fixtures des tests de services du catalogue : mêmes que `tests/api` (base db-test)."""

from tests.api.conftest import (  # noqa: F401  (fixtures réexportées pour pytest)
    World,
    api,
    api_migrated,
    db_conn,
    db_session,
    headers,
    world,
)
