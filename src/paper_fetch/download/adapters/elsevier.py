"""Elsevier / ScienceDirect adapter."""
from __future__ import annotations

from typing import TYPE_CHECKING

from paper_fetch.download.adapters.base import dismiss_common_banners

if TYPE_CHECKING:
    from playwright.async_api import ElementHandle, Page


class ElsevierAdapter:
    name = "elsevier"
    domain_patterns = ["sciencedirect.com", "elsevier.com"]

    async def pre_click_hook(self, page: "Page") -> None:
        await dismiss_common_banners(page)
        # ScienceDirect frequently shows a "Show PDF" button rather than a link.

    async def locate_pdf_element(self, page: "Page") -> "ElementHandle | None":
        # Primary: the "View PDF" button in the paper toolbar.
        for sel in (
            'a[aria-label*="Download PDF" i]',
            'a.download-pdf-link',
            'a[aria-label="View PDF"]',
            'a:has-text("View PDF")',
            'button:has-text("View PDF")',
            'a.pdf-download-btn',
        ):
            el = await page.query_selector(sel)
            if el:
                return el
        return None
