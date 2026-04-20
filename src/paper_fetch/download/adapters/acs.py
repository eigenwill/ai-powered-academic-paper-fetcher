"""American Chemical Society (pubs.acs.org) adapter."""
from __future__ import annotations

from typing import TYPE_CHECKING

from paper_fetch.download.adapters.base import dismiss_common_banners

if TYPE_CHECKING:
    from playwright.async_api import ElementHandle, Page


class ACSAdapter:
    name = "acs"
    domain_patterns = ["pubs.acs.org", "acs.org"]

    async def pre_click_hook(self, page: "Page") -> None:
        await dismiss_common_banners(page)

    async def locate_pdf_element(self, page: "Page") -> "ElementHandle | None":
        for sel in (
            'a[href*="/doi/pdf/"]',
            'a[title*="PDF"]',
            'a.pdf-link',
            'a:has-text("PDF")',
        ):
            el = await page.query_selector(sel)
            if el:
                return el
        return None
