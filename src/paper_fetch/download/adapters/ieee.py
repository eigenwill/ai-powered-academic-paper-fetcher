"""IEEE Xplore adapter."""
from __future__ import annotations

from typing import TYPE_CHECKING

from paper_fetch.download.adapters.base import dismiss_common_banners

if TYPE_CHECKING:
    from playwright.async_api import ElementHandle, Page


class IEEEAdapter:
    name = "ieee"
    domain_patterns = ["ieeexplore.ieee.org", "ieee.org"]

    async def pre_click_hook(self, page: "Page") -> None:
        await dismiss_common_banners(page)

    async def locate_pdf_element(self, page: "Page") -> "ElementHandle | None":
        # IEEE uses a stamp.jsp URL that serves Content-Disposition: attachment.
        for sel in (
            'a[href*="stamp.jsp"]',
            'a.pdf-btn-link',
            'a[aria-label*="PDF"]',
            'a:has-text("PDF")',
        ):
            el = await page.query_selector(sel)
            if el:
                return el
        return None
