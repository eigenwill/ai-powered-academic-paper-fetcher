"""Thin `diskcache` wrapper with typed helpers for our specific namespaces.

Namespaces (key prefixes):
- `s2:<sha1-of-query>`       → Semantic Scholar search response (TTL 7d)
- `unpaywall:<doi>`          → Unpaywall response (TTL 30d)
- `pdf:<doi>`                → absolute path to cached PDF (no TTL)
- `crossref:<doi>`           → CrossRef record (TTL 30d)
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import diskcache

_DAY = 24 * 60 * 60
TTL_S2 = 7 * _DAY
TTL_UNPAYWALL = 30 * _DAY
TTL_CROSSREF = 30 * _DAY


class Cache:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self._c = diskcache.Cache(str(directory))

    # --- generic ---
    def get(self, key: str) -> Any:
        return self._c.get(key)

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        self._c.set(key, value, expire=ttl)

    def delete(self, key: str) -> None:
        self._c.delete(key)

    def clear(self) -> int:
        return self._c.clear()

    # --- namespaced helpers ---
    @staticmethod
    def s2_key(query: str, limit: int) -> str:
        h = hashlib.sha1(f"{query}|{limit}".encode("utf-8")).hexdigest()
        return f"s2:{h}"

    @staticmethod
    def unpaywall_key(doi: str) -> str:
        return f"unpaywall:{doi.lower()}"

    @staticmethod
    def crossref_key(doi: str) -> str:
        return f"crossref:{doi.lower()}"

    @staticmethod
    def pdf_key(doi: str) -> str:
        return f"pdf:{doi.lower()}"

    def close(self) -> None:
        self._c.close()
