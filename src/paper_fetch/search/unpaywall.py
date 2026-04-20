"""Unpaywall lookup — cheap OA PDF discovery keyed by DOI.

https://api.unpaywall.org/v2/{doi}?email=you@example.com
"""
from __future__ import annotations

import logging
from typing import Any

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from paper_fetch.cache import TTL_UNPAYWALL, Cache

logger = logging.getLogger(__name__)

UNPAYWALL_BASE = "https://api.unpaywall.org/v2"


class Unpaywall:
    def __init__(self, email: str, cache: Cache | None = None):
        if not email:
            raise ValueError("Unpaywall requires a contact email.")
        self.email = email
        self.cache = cache

    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        retry=retry_if_exception_type(requests.RequestException),
    )
    def _get(self, doi: str) -> dict[str, Any] | None:
        url = f"{UNPAYWALL_BASE}/{doi}"
        logger.debug("Unpaywall GET %s", url)
        r = requests.get(url, params={"email": self.email}, timeout=20)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def lookup(self, doi: str) -> str | None:
        """Return the best OA PDF URL for this DOI, or None."""
        if not doi:
            return None
        if self.cache is not None:
            cached = self.cache.get(Cache.unpaywall_key(doi))
            if cached is not None:
                return self._extract_pdf_url(cached)

        try:
            data = self._get(doi)
        except Exception as e:
            logger.warning("Unpaywall lookup failed for %s: %s", doi, e)
            return None
        if data is None:
            return None
        if self.cache is not None:
            self.cache.set(Cache.unpaywall_key(doi), data, ttl=TTL_UNPAYWALL)
        return self._extract_pdf_url(data)

    @staticmethod
    def _extract_pdf_url(data: dict[str, Any]) -> str | None:
        best = data.get("best_oa_location")
        if best and best.get("url_for_pdf"):
            return best["url_for_pdf"]
        # Fallback: scan all oa_locations for any url_for_pdf
        for loc in data.get("oa_locations") or []:
            if loc.get("url_for_pdf"):
                return loc["url_for_pdf"]
        return None
