"""Limiteur d'échecs en mémoire (SA-28) : 5 échecs de connexion / 15 min / IP + e-mail.

Compteur **par processus** (suffisant pour le socle : un seul worker uvicorn). Avec
plusieurs workers ou instances, le déplacer dans PostgreSQL ou Redis (SA-4 n'a pas de Redis).
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock


class FailureLimiter:
    """Fenêtre glissante : refuse quand `max_failures` échecs sont dans les `window_s` dernières
    secondes. Un succès efface les échecs de la clé."""

    def __init__(self, max_failures: int, window_s: int) -> None:
        self.max_failures = max_failures
        self.window_s = window_s
        self._failures: dict[str, deque[float]] = {}
        self._lock = Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        bucket = self._failures.setdefault(key, deque())
        while bucket and bucket[0] <= now - self.window_s:
            bucket.popleft()
        return bucket

    def retry_after(self, key: str, now: float | None = None) -> int | None:
        """Secondes avant un nouvel essai si la clé est bloquée, sinon None."""
        now = time.monotonic() if now is None else now
        with self._lock:
            bucket = self._prune(key, now)
            if len(bucket) < self.max_failures:
                return None
            return max(1, int(bucket[0] + self.window_s - now) + 1)

    def record_failure(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._prune(key, now).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
