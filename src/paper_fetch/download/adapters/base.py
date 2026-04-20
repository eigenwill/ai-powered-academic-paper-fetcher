"""Publisher adapter protocol.

Adapters are intentionally thin: they describe *what to click* for a given
publisher. The actual "now wait for bytes" plumbing lives in `vpn.py`.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from playwright.async_api import ElementHandle, Page


class PublisherAdapter(Protocol):
    name: str
    domain_patterns: list[str]

    async def pre_click_hook(self, page: "Page") -> None: ...

    async def locate_pdf_element(self, page: "Page") -> "ElementHandle | None": ...


async def dismiss_common_banners(page) -> None:
    """Best-effort cookie / consent / interstitial dismissal.

    All failures are swallowed — missing a banner is not a reason to bail.
    """
    selectors = [
        'button[id*="cookie" i][id*="accept" i]',
        'button[class*="cookie" i][class*="accept" i]',
        'button:has-text("Accept All")',
        'button:has-text("I Accept")',
        'button:has-text("Accept all cookies")',
        'button:has-text("Got it")',
        '#onetrust-accept-btn-handler',
    ]
    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                await el.click(timeout=1000)
        except Exception:
            pass
