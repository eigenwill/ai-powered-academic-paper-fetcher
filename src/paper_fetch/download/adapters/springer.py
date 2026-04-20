"""SpringerLink / Nature family adapter."""
from __future__ import annotations

from typing import TYPE_CHECKING

from paper_fetch.download.adapters.base import dismiss_common_banners

if TYPE_CHECKING:
    from playwright.async_api import ElementHandle, Page


class SpringerAdapter:
    name = "springer"
    domain_patterns = ["link.springer.com", "springer.com", "nature.com"]

    async def pre_click_hook(self, page: "Page") -> None:
        await dismiss_common_banners(page)

    async def locate_pdf_element(self, page: "Page") -> "ElementHandle | None":
        for sel in (
            'a[data-track-action="download pdf"]',
            'a.c-pdf-download__link',
            'a[data-article-pdf]',
            'a[href*="/content/pdf/"]',
            'a[href$=".pdf"]',
            'a:has-text("Download PDF")',
        ):
            el = await page.query_selector(sel)
            if el:
                return el
        return None
