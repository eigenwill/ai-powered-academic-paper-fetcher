"""Shared data types.

These dataclasses are the shape every module agrees on. Search providers
produce `PaperMetadata`; downloaders produce `DownloadResult`; the pipeline
hands both to the Zotero client.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PaperMetadata:
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    abstract: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    s2_paper_id: str | None = None
    venue: str | None = None
    open_access_pdf_url: str | None = None       # from Semantic Scholar
    unpaywall_pdf_url: str | None = None
    external_ids: dict = field(default_factory=dict)

    @property
    def canonical_url(self) -> str | None:
        """Best canonical URL for this paper — preferred by VPN Route B."""
        if self.doi:
            return f"https://doi.org/{self.doi}"
        if self.arxiv_id:
            return f"https://arxiv.org/abs/{self.arxiv_id}"
        return None

    @property
    def slug(self) -> str:
        """Filename-safe slug for downloaded PDFs."""
        base = self.doi or self.arxiv_id or self.title
        s = re.sub(r"[^\w\-]+", "_", base)
        return s.strip("_")[:120] or "paper"

    def candidate_pdf_urls(self) -> list[str]:
        """PDF URLs Route A should try, in order of preference."""
        urls: list[str] = []
        if self.unpaywall_pdf_url:
            urls.append(self.unpaywall_pdf_url)
        if self.open_access_pdf_url:
            urls.append(self.open_access_pdf_url)
        if self.arxiv_id:
            # Normalize arxiv id (strip any "vN" versioning for the PDF URL)
            aid = self.arxiv_id
            urls.append(f"https://arxiv.org/pdf/{aid}.pdf")
        # Deduplicate while preserving order
        seen: set[str] = set()
        ordered: list[str] = []
        for u in urls:
            if u and u not in seen:
                seen.add(u)
                ordered.append(u)
        return ordered


@dataclass
class DownloadResult:
    success: bool
    path: Path | None = None
    route: str = "failed"            # "direct-s2" | "direct-unpaywall" | "direct-arxiv" | "vpn" | "failed"
    publisher: str | None = None
    error: str | None = None
