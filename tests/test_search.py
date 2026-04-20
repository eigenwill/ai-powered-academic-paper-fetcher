"""Unit tests for search providers.

These tests mock `requests` so we never hit the live S2/Unpaywall/CrossRef APIs.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests


# ---------------------------------------------------------------------------
# Semantic Scholar
# ---------------------------------------------------------------------------
def test_s2_search_parses_metadata():
    from paper_fetch.search.semantic_scholar import SemanticScholar

    fake = {
        "data": [
            {
                "title": "Foo",
                "authors": [{"name": "A. Smith"}, {"name": "B. Jones"}],
                "year": 2021,
                "abstract": "summary",
                "externalIds": {"DOI": "10.1/abc", "ArXiv": "2101.00001"},
                "openAccessPdf": {"url": "https://arxiv.org/pdf/2101.00001.pdf"},
                "venue": "ICML",
                "paperId": "pid",
            }
        ]
    }

    with patch("paper_fetch.search.semantic_scholar.requests.get") as gm:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = fake
        resp.raise_for_status.return_value = None
        gm.return_value = resp

        s2 = SemanticScholar(api_key=None)
        out = s2.search("foo", limit=1)

    assert len(out) == 1
    m = out[0]
    assert m.title == "Foo"
    assert m.authors == ["A. Smith", "B. Jones"]
    assert m.doi == "10.1/abc"
    assert m.arxiv_id == "2101.00001"
    assert m.open_access_pdf_url == "https://arxiv.org/pdf/2101.00001.pdf"
    assert m.s2_paper_id == "pid"


def test_s2_by_doi_returns_none_on_404():
    from paper_fetch.search.semantic_scholar import SemanticScholar

    with patch("paper_fetch.search.semantic_scholar.requests.get") as gm:
        resp = MagicMock()
        resp.status_code = 404
        http_err = requests.HTTPError(response=MagicMock(status_code=404))
        http_err.response = MagicMock(status_code=404)
        resp.raise_for_status.side_effect = http_err
        gm.return_value = resp

        s2 = SemanticScholar(api_key=None)
        assert s2.by_doi("10.9999/nope") is None


# ---------------------------------------------------------------------------
# Unpaywall
# ---------------------------------------------------------------------------
def test_unpaywall_extracts_best_oa_pdf():
    from paper_fetch.search.unpaywall import Unpaywall

    fake = {
        "best_oa_location": {"url_for_pdf": "https://oa.example/pdf"},
        "oa_locations": [{"url_for_pdf": "https://other.example/pdf"}],
    }
    with patch("paper_fetch.search.unpaywall.requests.get") as gm:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = fake
        resp.raise_for_status.return_value = None
        gm.return_value = resp

        u = Unpaywall(email="t@e.com")
        url = u.lookup("10.1/abc")
    assert url == "https://oa.example/pdf"


def test_unpaywall_falls_back_to_oa_locations_when_no_best():
    from paper_fetch.search.unpaywall import Unpaywall

    fake = {"best_oa_location": None, "oa_locations": [{"url_for_pdf": "https://fb.example/pdf"}]}
    with patch("paper_fetch.search.unpaywall.requests.get") as gm:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = fake
        resp.raise_for_status.return_value = None
        gm.return_value = resp

        u = Unpaywall(email="t@e.com")
        assert u.lookup("10.1/abc") == "https://fb.example/pdf"


def test_unpaywall_returns_none_on_404():
    from paper_fetch.search.unpaywall import Unpaywall

    with patch("paper_fetch.search.unpaywall.requests.get") as gm:
        resp = MagicMock()
        resp.status_code = 404
        gm.return_value = resp

        u = Unpaywall(email="t@e.com")
        assert u.lookup("10.1/nope") is None


def test_unpaywall_requires_email():
    from paper_fetch.search.unpaywall import Unpaywall

    with pytest.raises(ValueError):
        Unpaywall(email="")


# ---------------------------------------------------------------------------
# CrossRef
# ---------------------------------------------------------------------------
def test_crossref_parses_metadata():
    from paper_fetch.search.crossref import CrossRef

    fake = {
        "message": {
            "title": ["A Paper"],
            "author": [{"given": "Jane", "family": "Doe"}, {"family": "Roe"}],
            "issued": {"date-parts": [[2020]]},
            "DOI": "10.1/xyz",
            "container-title": ["Nature"],
        }
    }
    with patch("paper_fetch.search.crossref.requests.get") as gm:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = fake
        resp.raise_for_status.return_value = None
        gm.return_value = resp

        cr = CrossRef("me@example.com")
        m = cr.by_doi("10.1/xyz")

    assert m is not None
    assert m.title == "A Paper"
    assert "Jane Doe" in m.authors
    assert "Roe" in m.authors
    assert m.year == 2020
    assert m.venue == "Nature"
