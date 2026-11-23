"""Hachage des mots de passe (SA-28) : Argon2id (SA-13 `user_account.password_hash`).

Bibliothèque `argon2-cffi` (paramètres par défaut RFC 9106, profil « low memory »). Le hash
contient l'algorithme, les paramètres et le sel : `$argon2id$v=19$m=...,t=...,p=...$...`.
Un hash d'un autre format (ex. marqueur des comptes seed) ne correspond jamais.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

#: Longueurs admises (SA-5 RegisterRequest : 10 minimum ; 128 maximum contre les abus).
PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128

_hasher = PasswordHasher()

#: Hash factice : la vérification d'un e-mail inconnu prend le même temps qu'un vrai échec.
_DUMMY_HASH = _hasher.hash("smartcampus-dummy-password")


def hash_password(password: str) -> str:
    """Hash Argon2id avec sel aléatoire ; jamais de mot de passe en clair."""
    return _hasher.hash(password)


def verify_password(password: str, encoded: str | None) -> bool:
    """Vrai si le mot de passe correspond. `encoded=None` : calcul factice, renvoie faux."""
    try:
        return _hasher.verify(encoded or _DUMMY_HASH, password) and encoded is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(encoded: str) -> bool:
    """Vrai si les paramètres du hash sont plus faibles que les paramètres actuels."""
    try:
        return _hasher.check_needs_rehash(encoded)
    except InvalidHashError:
        return False
