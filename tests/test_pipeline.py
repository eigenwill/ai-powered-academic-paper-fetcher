"""End-to-end pipeline tests — all external I/O mocked out."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from paper_fetch.models import DownloadResult, PaperMetadata


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("DOWNLOAD_DIR", str(tmp_path / "dl"))
    from paper_fetch.config import load_settings

    s = load_settings()
    s.ensure_dirs()
    return s


async def test_dry_run_prints_metadata_and_skips_download(settings, sample_meta):
    from paper_fetch import pipeline

    with (
        patch.object(pipeline.SemanticScholar, "search", return_value=[sample_meta]),
        patch.object(pipeline.Unpaywall, "lookup", return_value=None),
        patch.object(pipeline, "_pick", return_value=sample_meta),
        patch("paper_fetch.download.direct.download") as dl,
        patch("paper_fetch.zotero_client.zotero.Zotero") as ZM,
    ):
        await pipeline.run_pipeline(
            "transformers", settings=settings, top_n=1, dry_run=True, use_vpn=False
        )

    dl.assert_not_called()
    ZM.return_value.create_items.assert_not_called()


async def test_route_a_happy_path_pushes_to_zotero(settings, sample_meta, tmp_path):
    from paper_fetch import pipeline

    pdf_path = tmp_path / "dl" / "x.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF-1.4\n")

    with (
        patch.object(pipeline.SemanticScholar, "search", return_value=[sample_meta]),
        patch.object(pipeline.Unpaywall, "lookup", return_value=None),
        patch.object(pipeline, "_pick", return_value=sample_meta),
        patch(
            "paper_fetch.pipeline.direct_download.download",
            return_value=DownloadResult(
                success=True, path=pdf_path, route="direct-arxiv"
            ),
        ),
        patch("paper_fetch.zotero_client.zotero.Zotero") as ZM,
    ):
        instance = ZM.return_value
        instance.items.return_value = []  # no DOI duplicate
        instance.item_template.return_value = {
            "title": "",
            "creators": [],
            "date": "",
            "DOI": "",
            "abstractNote": "",
            "publicationTitle": "",
            "url": "",
            "extra": "",
        }
        instance.create_items.return_value = {
            "successful": {"0": {"key": "KEY1"}},
            "failed": {},
        }
        await pipeline.run_pipeline(
            "transformers", settings=settings, top_n=1, use_vpn=False
        )

    # PDF was attached.
    instance.attachment_simple.assert_called_once()


async def test_route_a_failure_creates_needs_pdf_tag_when_no_vpn(settings, sample_meta):
    from paper_fetch import pipeline

    with (
        patch.object(pipeline.SemanticScholar, "search", return_value=[sample_meta]),
        patch.object(pipeline.Unpaywall, "lookup", return_value=None),
        patch.object(pipeline, "_pick", return_value=sample_meta),
        patch(
            "paper_fetch.pipeline.direct_download.download",
            return_value=DownloadResult(success=False, route="failed", error="nope"),
        ),
        patch("paper_fetch.zotero_client.zotero.Zotero") as ZM,
    ):
        instance = ZM.return_value
        instance.items.return_value = []
        instance.item_template.return_value = {
            "title": "",
            "creators": [],
            "date": "",
            "DOI": "",
            "abstractNote": "",
            "publicationTitle": "",
            "url": "",
            "extra": "",
        }
        instance.create_items.return_value = {
            "successful": {"0": {"key": "KEY2"}},
            "failed": {},
        }
        await pipeline.run_pipeline(
            "transformers", settings=settings, top_n=1, use_vpn=False
        )

    payload = instance.create_items.call_args[0][0][0]
    assert payload["tags"] == [{"tag": "needs-pdf"}]
    instance.attachment_simple.assert_not_called()
