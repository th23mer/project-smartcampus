"""Pagination SA-5 §1.5.

- Listes : `?page=1&page_size=20` (défaut 20, max 100) →
  `{"items": [...], "meta": {"page", "page_size", "total_items", "total_pages"}}`.
- Messages de chat : curseur `?before=<curseur>&limit=20` →
  `{"items": [...], "meta": {"limit", "next_cursor"}}`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends, Query
from pydantic import BaseModel, Field

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


class PageParams(BaseModel):
    """Paramètres de pagination par numéro de page."""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


def page_params(
    page: Annotated[int, Query(ge=1, description="Numéro de page (à partir de 1).")] = 1,
    page_size: Annotated[
        int,
        Query(ge=1, le=MAX_PAGE_SIZE, description="Taille de page (défaut 20, max 100)."),
    ] = DEFAULT_PAGE_SIZE,
) -> PageParams:
    """Dépendance FastAPI : paramètres `page` et `page_size` validés."""
    return PageParams(page=page, page_size=page_size)


PageParamsDep = Annotated[PageParams, Depends(page_params)]


class PageMeta(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class Page[T](BaseModel):
    """Enveloppe d'une liste paginée."""

    items: list[T]
    meta: PageMeta

    @classmethod
    def build(cls, items: Sequence[T], total_items: int, params: PageParams) -> Page[T]:
        total_pages = math.ceil(total_items / params.page_size) if total_items else 0
        return cls(
            items=list(items),
            meta=PageMeta(
                page=params.page,
                page_size=params.page_size,
                total_items=total_items,
                total_pages=total_pages,
            ),
        )


class CursorParams(BaseModel):
    before: str | None = None
    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)


def cursor_params(
    before: Annotated[str | None, Query(description="Curseur opaque de la page suivante.")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> CursorParams:
    """Dépendance FastAPI : pagination par curseur (messages de chat)."""
    return CursorParams(before=before, limit=limit)


CursorParamsDep = Annotated[CursorParams, Depends(cursor_params)]


class CursorMeta(BaseModel):
    limit: int
    next_cursor: str | None


class CursorPage[T](BaseModel):
    """Enveloppe d'une liste paginée par curseur."""

    items: list[T]
    meta: CursorMeta
