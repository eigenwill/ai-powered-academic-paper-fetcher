"""Per-publisher adapters for Route B.

Each adapter knows how to: (1) dismiss nuisance UI (cookie banners, paywall
overlays), (2) locate the element that triggers a PDF fetch. The VPN
downloader handles what happens *after* the click — response interception
or expect_download — uniformly.
"""
from __future__ import annotations

from paper_fetch.download.adapters.acs import ACSAdapter
from paper_fetch.download.adapters.base import PublisherAdapter
from paper_fetch.download.adapters.elsevier import ElsevierAdapter
from paper_fetch.download.adapters.generic import GenericAdapter
from paper_fetch.download.adapters.ieee import IEEEAdapter
from paper_fetch.download.adapters.springer import SpringerAdapter
from paper_fetch.download.adapters.wiley import WileyAdapter

REGISTRY: list[type[PublisherAdapter]] = [
    ElsevierAdapter,
    SpringerAdapter,
    WileyAdapter,
    IEEEAdapter,
    ACSAdapter,
    # GenericAdapter must be last — it matches anything.
    GenericAdapter,
]


def pick_adapter(url: str) -> PublisherAdapter:
    for cls in REGISTRY:
        if any(pat in url for pat in cls.domain_patterns):
            return cls()
    return GenericAdapter()


__all__ = ["PublisherAdapter", "REGISTRY", "pick_adapter"]
