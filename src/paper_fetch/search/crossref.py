"""CrossRef fallback — used when the user passes a bare DOI and S2 returns nothing.

CrossRef etiquette: include a contact-capable User-Agent.
"""
from __future__ import annotations

import logging
from typing import Any

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from paper_fetch.cache import TTL_CROSSREF, Cache
from paper_fetch.models import PaperMetadata

logger = logging.getLogger(__name__)

CROSSREF_BASE = "https://api.crossref.org/works"


def _ua(email: str | None) -> str:
    if email:
        return f"paper-fetch/0.1 (mailto:{email})"
    return "paper-fetch/0.1"


class CrossRef:
    def __init__(self, contact_email: str | None = None, cache: Cache | None = None):
        self.email = contact_email
        self.cache = cache

    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        retry=retry_if_exception_type(requests.RequestException),
    )
    def _get(self, doi: str) -> dict[str, Any] | None:
        url = f"{CROSSREF_BASE}/{doi}"
        logger.debug("CrossRef GET %s", url)
        r = requests.get(url, headers={"User-Agent": _ua(self.email)}, timeout=20)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def by_doi(self, doi: str) -> PaperMetadata | None:
        if self.cache is not None:
            cached = self.cache.get(Cache.crossref_key(doi))
            if cached is not None:
                return self._to_metadata(cached)
        try:
            data = self._get(doi)
        except Exception as e:
            logger.warning("CrossRef lookup failed for %s: %s", doi, e)
            return None
        if data is None:
            return None
        if self.cache is not None:
            self.cache.set(Cache.crossref_key(doi), data, ttl=TTL_CROSSREF)
        return self._to_metadata(data)

    @staticmethod
    def _to_metadata(payload: dict[str, Any]) -> PaperMetadata:
        msg = payload.get("message") or {}
        title_list = msg.get("title") or []
        title = title_list[0] if title_list else "(untitled)"
        authors = []
        for a in msg.get("author") or []:
            given = a.get("given", "")
            family = a.get("family", "")
            name = " ".join(p for p in (given, family) if p).strip()
            if name:
                authors.append(name)
        # Try to pull a year
        year: int | None = None
        for key in ("published-print", "published-online", "issued"):
            parts = (msg.get(key) or {}).get("date-parts") or []
            if parts and parts[0]:
                year = parts[0][0]
                break
        venue_list = msg.get("container-title") or []
        venue = venue_list[0] if venue_list else None
        return PaperMetadata(
            title=title,
            authors=authors,
            year=year,
            abstract=msg.get("abstract"),
            doi=msg.get("DOI"),
            venue=venue,
        )
