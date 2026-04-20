"""Semantic Scholar Graph API client.

Docs: https://api.semanticscholar.org/api-docs/graph

We only use two endpoints:
- `/paper/search`   (keyword search, relevance-ranked)
- `/paper/{id}`     (by ID, used by `--doi`)
"""
from __future__ import annotations

import logging
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from paper_fetch.cache import TTL_S2, Cache
from paper_fetch.models import PaperMetadata

logger = logging.getLogger(__name__)

S2_BASE = "https://api.semanticscholar.org/graph/v1"
FIELDS = "title,authors,year,abstract,externalIds,openAccessPdf,venue,paperId"


class S2Error(Exception):
    pass


def _headers(api_key: str | None) -> dict[str, str]:
    h = {"Accept": "application/json", "User-Agent": "paper-fetch/0.1"}
    if api_key:
        h["x-api-key"] = api_key
    return h


def _to_metadata(record: dict[str, Any]) -> PaperMetadata:
    authors_raw = record.get("authors") or []
    authors = [a.get("name", "") for a in authors_raw if a.get("name")]
    external_ids = record.get("externalIds") or {}
    doi = external_ids.get("DOI")
    arxiv = external_ids.get("ArXiv")
    oa = record.get("openAccessPdf") or {}
    return PaperMetadata(
        title=record.get("title") or "(untitled)",
        authors=authors,
        year=record.get("year"),
        abstract=record.get("abstract"),
        doi=doi,
        arxiv_id=arxiv,
        s2_paper_id=record.get("paperId"),
        venue=record.get("venue"),
        open_access_pdf_url=oa.get("url"),
        external_ids=external_ids,
    )


class SemanticScholar:
    def __init__(self, api_key: str | None, cache: Cache | None = None):
        self.api_key = api_key
        self.cache = cache

    @retry(
        reraise=True,
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        retry=retry_if_exception_type((requests.RequestException, S2Error)),
    )
    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{S2_BASE}{path}"
        logger.debug("S2 GET %s params=%s", url, params)
        r = requests.get(url, params=params, headers=_headers(self.api_key), timeout=30)
        if r.status_code in (429, 502, 503, 504):
            raise S2Error(f"S2 transient status {r.status_code}: {r.text[:200]}")
        r.raise_for_status()
        return r.json()

    def search(self, query: str, limit: int = 5) -> list[PaperMetadata]:
        if self.cache is not None:
            key = Cache.s2_key(query, limit)
            cached = self.cache.get(key)
            if cached is not None:
                logger.debug("S2 cache hit for %s", key)
                return [_to_metadata(r) for r in cached]

        data = self._get("/paper/search", {"query": query, "limit": limit, "fields": FIELDS})
        results = data.get("data") or []
        if self.cache is not None:
            self.cache.set(Cache.s2_key(query, limit), results, ttl=TTL_S2)
        return [_to_metadata(r) for r in results]

    def by_doi(self, doi: str) -> PaperMetadata | None:
        try:
            data = self._get(f"/paper/DOI:{doi}", {"fields": FIELDS})
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                return None
            raise
        return _to_metadata(data)

    def by_arxiv(self, arxiv_id: str) -> PaperMetadata | None:
        try:
            data = self._get(f"/paper/arXiv:{arxiv_id}", {"fields": FIELDS})
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                return None
            raise
        return _to_metadata(data)
