"""Zotero client — metadata upsert + PDF attachment.

The original spec assumed a "Zotero magic wand" that takes a DOI and fills
the rest. `pyzotero` doesn't ship with that; the magic wand in the Zotero
desktop app is a call out to the separate `zotero-translation-server`.

Given we *already* have structured metadata from Semantic Scholar /
Unpaywall / CrossRef, we skip the translation-server round trip and build
the Zotero item directly. An optional passthrough to a locally-running
translation-server is offered for users who want richer metadata.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pyzotero import zotero
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from paper_fetch.models import PaperMetadata

logger = logging.getLogger(__name__)


class ZoteroClient:
    def __init__(
        self,
        library_id: str,
        library_type: str,
        api_key: str,
    ):
        self.zot = zotero.Zotero(library_id, library_type, api_key)

    # --- basic ops ----------------------------------------------------------
    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=15),
        retry=retry_if_exception_type(Exception),
    )
    def ping(self) -> bool:
        """Cheap API check used by `paper-fetch init`."""
        self.zot.items(limit=1)
        return True

    # --- metadata ----------------------------------------------------------
    def build_item(self, meta: PaperMetadata) -> dict[str, Any]:
        template = self.zot.item_template("journalArticle")
        template["title"] = meta.title
        template["creators"] = _authors_to_creators(meta.authors)
        template["date"] = str(meta.year) if meta.year else ""
        template["DOI"] = meta.doi or ""
        template["abstractNote"] = meta.abstract or ""
        template["publicationTitle"] = meta.venue or ""
        template["url"] = meta.canonical_url or ""
        extras = []
        if meta.arxiv_id:
            extras.append(f"arXiv: {meta.arxiv_id}")
        if meta.s2_paper_id:
            extras.append(f"S2 paper ID: {meta.s2_paper_id}")
        template["extra"] = "\n".join(extras)
        return template

    # --- dedup + create ----------------------------------------------------
    def find_by_doi(self, doi: str) -> str | None:
        """Return an existing item key whose DOI matches, if any."""
        if not doi:
            return None
        try:
            hits = self.zot.items(q=doi, qmode="everything", limit=25)
        except Exception as e:
            logger.warning("Zotero DOI lookup failed: %s", e)
            return None
        for h in hits or []:
            data = h.get("data", {})
            if (data.get("DOI") or "").lower() == doi.lower():
                return h.get("key")
        return None

    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=15),
        retry=retry_if_exception_type(Exception),
    )
    def _create_item(self, payload: dict[str, Any]) -> str:
        resp = self.zot.create_items([payload])
        successful = resp.get("successful") or {}
        if not successful:
            failed = resp.get("failed") or {}
            raise RuntimeError(f"Zotero create failed: {failed}")
        first = next(iter(successful.values()))
        return first["key"]

    def upsert_item(self, meta: PaperMetadata, *, tags: list[str] | None = None) -> str:
        """Create a new item, or return the existing key if DOI matches."""
        if meta.doi:
            existing = self.find_by_doi(meta.doi)
            if existing:
                logger.info("Zotero duplicate found for DOI %s → %s", meta.doi, existing)
                if tags:
                    self._merge_tags(existing, tags)
                return existing
        payload = self.build_item(meta)
        if tags:
            payload["tags"] = [{"tag": t} for t in tags]
        key = self._create_item(payload)
        logger.info("Created Zotero item %s", key)
        return key

    def _merge_tags(self, item_key: str, tags: list[str]) -> None:
        try:
            item = self.zot.item(item_key)
            existing = {t.get("tag") for t in (item["data"].get("tags") or [])}
            new_tags = [t for t in tags if t not in existing]
            if not new_tags:
                return
            item["data"]["tags"] = (item["data"].get("tags") or []) + [
                {"tag": t} for t in new_tags
            ]
            self.zot.update_item(item)
        except Exception as e:
            logger.warning("Could not merge tags on %s: %s", item_key, e)

    # --- attachments -------------------------------------------------------
    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=15),
        retry=retry_if_exception_type(Exception),
    )
    def attach_pdf(self, item_key: str, pdf_path: Path) -> None:
        self.zot.attachment_simple([str(pdf_path)], item_key)
        logger.info("Attached %s to %s", pdf_path.name, item_key)

    # --- retry-failed queue -------------------------------------------------
    def items_needing_pdf(self, tag: str = "needs-pdf") -> list[dict[str, Any]]:
        try:
            return list(self.zot.items(tag=tag, limit=100) or [])
        except Exception as e:
            logger.warning("Zotero tag query failed: %s", e)
            return []

    def remove_tag(self, item_key: str, tag: str) -> None:
        try:
            item = self.zot.item(item_key)
            item["data"]["tags"] = [
                t for t in (item["data"].get("tags") or []) if t.get("tag") != tag
            ]
            self.zot.update_item(item)
        except Exception as e:
            logger.warning("Could not remove tag %s from %s: %s", tag, item_key, e)


# --- helpers ---------------------------------------------------------------
def _authors_to_creators(authors: list[str]) -> list[dict[str, str]]:
    creators: list[dict[str, str]] = []
    for name in authors:
        name = name.strip()
        if not name:
            continue
        # Try to split a "First Middle Last" name into firstName/lastName.
        if "," in name:
            last, first = (p.strip() for p in name.split(",", 1))
            creators.append({"creatorType": "author", "firstName": first, "lastName": last})
        elif " " in name:
            parts = name.rsplit(" ", 1)
            creators.append(
                {"creatorType": "author", "firstName": parts[0], "lastName": parts[1]}
            )
        else:
            creators.append({"creatorType": "author", "name": name})
    return creators
