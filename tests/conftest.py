"""Shared pytest fixtures."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    """Every test gets clean, isolated settings dirs."""
    monkeypatch.setenv("ZOTERO_API_KEY", "test-key")
    monkeypatch.setenv("ZOTERO_USER_ID", "99999")
    monkeypatch.setenv("ZOTERO_LIBRARY_TYPE", "user")
    monkeypatch.setenv("UNPAYWALL_EMAIL", "test@example.com")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("DOWNLOAD_DIR", str(tmp_path / "downloads"))
    monkeypatch.setenv(
        "PLAYWRIGHT_USER_DATA_DIR", str(tmp_path / "chromium-profile")
    )
    yield


@pytest.fixture
def sample_meta():
    from paper_fetch.models import PaperMetadata

    return PaperMetadata(
        title="Attention Is All You Need",
        authors=["Ashish Vaswani", "Noam Shazeer"],
        year=2017,
        abstract="We propose a new simple network architecture…",
        doi="10.48550/arXiv.1706.03762",
        arxiv_id="1706.03762",
        s2_paper_id="204e3073870fae3d05bcbc2f6a8e263d9b72e776",
        venue="NeurIPS",
        open_access_pdf_url="https://arxiv.org/pdf/1706.03762.pdf",
    )
