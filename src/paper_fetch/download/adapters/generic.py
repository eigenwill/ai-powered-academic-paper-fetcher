"""Fallback adapter used when no publisher pattern matches.

Strategy: find any clickable element whose visible text or `href` looks
PDF-shaped. This is the workhorse for long-tail publishers and OA
repositories.
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from paper_fetch.download.adapters.base import dismiss_common_banners

if TYPE_CHECKING:
    from playwright.async_api import ElementHandle, Page

logger = logging.getLogger(__name__)

_TEXT_RE = re.compile(r"\b(pdf|full[\s\-]?text|download)\b", re.I)


class GenericAdapter:
    name = "generic"
    domain_patterns: list[str] = [""]  # matches anything (fallback)

    async def pre_click_hook(self, page: "Page") -> None:
        await dismiss_common_banners(page)

    async def locate_pdf_element(self, page: "Page") -> "ElementHandle | None":
        # 1. Direct anchors that end in .pdf
        el = await page.query_selector('a[href$=".pdf"]')
        if el:
            return el

        # 2. Any anchor whose text is PDF-ish and is reasonably prominent
        anchors = await page.query_selector_all("a")
        for a in anchors:
            try:
                text = (await a.inner_text() or "").strip()
            except Exception:
                continue
            if text and _TEXT_RE.search(text):
                return a

        # 3. Anchors with PDF-ish aria labels or titles
        for attr in ("aria-label", "title"):
            el = await page.query_selector(f'a[{attr}*="pdf" i], a[{attr}*="download" i]')
            if el:
                return el

        logger.debug("generic adapter found no PDF element at %s", page.url)
        return None
