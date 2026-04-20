"""Route A tests — mock `requests.get` to fake PDF / HTML streams."""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch


@contextmanager
def _mock_stream(chunks, status=200, content_type="application/pdf"):
    resp = MagicMock()
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    resp.status_code = status
    resp.headers = {"content-type": content_type}

    def iter_content(chunk_size):
        yield from chunks

    resp.iter_content = iter_content
    with patch("paper_fetch.download.direct.requests.get", return_value=resp):
        yield resp


def test_direct_download_succeeds_on_pdf(tmp_path, sample_meta):
    from paper_fetch.download import direct

    body = b"%PDF-1.4\n" + (b"X" * 10_000)
    # Split into two chunks to exercise the loop.
    chunks = [body[:1024], body[1024:]]
    with _mock_stream(chunks):
        result = direct.download(sample_meta, tmp_path)

    assert result.success, result.error
    assert result.path is not None
    assert result.path.exists()
    assert result.path.read_bytes().startswith(b"%PDF-")
    assert result.route == "direct-s2" or result.route.startswith("direct")


def test_direct_download_rejects_html_landing_page(tmp_path, sample_meta):
    """If Route A's URL secretly returns HTML, we must abort and not save it."""
    from paper_fetch.download import direct

    # No arxiv_id so we only try one URL (the S2 one) — simplifies the assertion.
    meta = sample_meta
    meta.arxiv_id = None
    meta.unpaywall_pdf_url = None
    chunks = [b"<!doctype html><html><head>...", b"</head></html>"]
    with _mock_stream(chunks, content_type="text/html"):
        result = direct.download(meta, tmp_path)

    assert not result.success
    assert "not a PDF" in (result.error or "")


def test_direct_download_reports_no_oa(tmp_path):
    """Paper with no OA URLs should exit Route A immediately."""
    from paper_fetch.download import direct
    from paper_fetch.models import PaperMetadata

    meta = PaperMetadata(title="x")
    result = direct.download(meta, tmp_path)
    assert not result.success
    assert result.route == "failed"
    assert "no OA URL" in (result.error or "")


def test_write_pdf_bytes_requires_magic(tmp_path, sample_meta):
    from paper_fetch.download import direct
    import pytest

    with pytest.raises(ValueError):
        direct.write_pdf_bytes(b"not a pdf", sample_meta, tmp_path)
