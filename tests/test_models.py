"""PaperMetadata shape & behavior."""
from __future__ import annotations


def test_canonical_url_prefers_doi():
    from paper_fetch.models import PaperMetadata

    m = PaperMetadata(title="x", doi="10.1/y", arxiv_id="1234.5678")
    assert m.canonical_url == "https://doi.org/10.1/y"


def test_canonical_url_falls_back_to_arxiv():
    from paper_fetch.models import PaperMetadata

    m = PaperMetadata(title="x", arxiv_id="1234.5678")
    assert m.canonical_url == "https://arxiv.org/abs/1234.5678"


def test_candidate_pdf_urls_order():
    from paper_fetch.models import PaperMetadata

    m = PaperMetadata(
        title="x",
        arxiv_id="2101.0001",
        open_access_pdf_url="https://s2.example/a.pdf",
        unpaywall_pdf_url="https://unp.example/b.pdf",
    )
    urls = m.candidate_pdf_urls()
    assert urls[0] == "https://unp.example/b.pdf"
    assert urls[1] == "https://s2.example/a.pdf"
    assert urls[2] == "https://arxiv.org/pdf/2101.0001.pdf"


def test_candidate_pdf_urls_dedup():
    from paper_fetch.models import PaperMetadata

    m = PaperMetadata(
        title="x",
        open_access_pdf_url="https://s2.example/a.pdf",
        unpaywall_pdf_url="https://s2.example/a.pdf",
    )
    assert m.candidate_pdf_urls() == ["https://s2.example/a.pdf"]


def test_slug_is_filename_safe():
    from paper_fetch.models import PaperMetadata

    m = PaperMetadata(title="A Paper", doi="10.1/x y: z?")
    assert m.slug.isascii()
    assert "/" not in m.slug
    assert "?" not in m.slug
