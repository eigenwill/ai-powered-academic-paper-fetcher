"""Zotero client tests — `pyzotero.Zotero` is mocked out."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_build_item_maps_fields(sample_meta):
    from paper_fetch.zotero_client import ZoteroClient

    with patch("paper_fetch.zotero_client.zotero.Zotero") as ZM:
        instance = ZM.return_value
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
        c = ZoteroClient("123", "user", "key")
        item = c.build_item(sample_meta)

    assert item["title"] == sample_meta.title
    assert item["DOI"] == sample_meta.doi
    assert item["date"] == "2017"
    assert item["publicationTitle"] == "NeurIPS"
    # Creators should be structured dicts.
    assert item["creators"][0]["creatorType"] == "author"
    # First author "Ashish Vaswani" should split into firstName/lastName.
    assert item["creators"][0]["lastName"] == "Vaswani"
    assert "arXiv: 1706.03762" in item["extra"]


def test_find_by_doi_returns_key_on_match(sample_meta):
    from paper_fetch.zotero_client import ZoteroClient

    with patch("paper_fetch.zotero_client.zotero.Zotero") as ZM:
        instance = ZM.return_value
        instance.items.return_value = [
            {"key": "ABCD1234", "data": {"DOI": sample_meta.doi}}
        ]
        c = ZoteroClient("123", "user", "key")
        k = c.find_by_doi(sample_meta.doi)
    assert k == "ABCD1234"


def test_upsert_creates_when_no_duplicate(sample_meta):
    from paper_fetch.zotero_client import ZoteroClient

    with patch("paper_fetch.zotero_client.zotero.Zotero") as ZM:
        instance = ZM.return_value
        instance.items.return_value = []  # no duplicate
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
            "successful": {"0": {"key": "NEWKEY"}},
            "failed": {},
        }
        c = ZoteroClient("123", "user", "key")
        key = c.upsert_item(sample_meta, tags=["needs-pdf"])

    assert key == "NEWKEY"
    # create_items was invoked with our payload including the tag.
    call_args = instance.create_items.call_args[0][0][0]
    assert call_args["tags"] == [{"tag": "needs-pdf"}]


def test_upsert_returns_existing_key_on_dup(sample_meta):
    from paper_fetch.zotero_client import ZoteroClient

    with patch("paper_fetch.zotero_client.zotero.Zotero") as ZM:
        instance = ZM.return_value
        instance.items.return_value = [
            {"key": "DUP", "data": {"DOI": sample_meta.doi, "tags": []}}
        ]
        instance.item.return_value = {
            "key": "DUP",
            "data": {"DOI": sample_meta.doi, "tags": []},
        }
        c = ZoteroClient("123", "user", "key")
        key = c.upsert_item(sample_meta, tags=["needs-pdf"])

    assert key == "DUP"
    instance.create_items.assert_not_called()
    # Tag merge path should have called update_item.
    instance.update_item.assert_called()
