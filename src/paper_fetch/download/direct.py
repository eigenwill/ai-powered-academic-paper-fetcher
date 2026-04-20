"""Route A: direct download with `requests`.

Only touches URLs we already know are OA (Unpaywall, S2 openAccessPdf, arXiv).
Paywall landing pages — HTML — are rejected via magic-byte check so a
"content-type: application/pdf" lie from the server can't smuggle through.
"""
from __future__ import annotations

import logging
from pathlib import Path

import requests

from paper_fetch.models import DownloadResult, PaperMetadata

logger = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"
_CHUNK = 64 * 1024
_MAX_BYTES = 100 * 1024 * 1024  # 100 MB safety limit
_HEADERS = {
    # Some servers refuse requests without a realistic UA.
    "User-Agent": (
        "Mozilla/5.0 (paper-fetch/0.1) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Safari/537.36"
    ),
    "Accept": "application/pdf,*/*;q=0.8",
}


def _is_pdf_head(chunk: bytes) -> bool:
    # Tolerate a few leading bytes (BOM/whitespace) before the signature.
    return PDF_MAGIC in chunk[:1024]


def _route_label(url: str, meta: PaperMetadata) -> str:
    if meta.unpaywall_pdf_url and url == meta.unpaywall_pdf_url:
        return "direct-unpaywall"
    if meta.open_access_pdf_url and url == meta.open_access_pdf_url:
        return "direct-s2"
    if "arxiv.org" in url:
        return "direct-arxiv"
    return "direct"


def download(meta: PaperMetadata, download_dir: Path) -> DownloadResult:
    """Try every candidate URL; return on first success."""
    candidates = meta.candidate_pdf_urls()
    if not candidates:
        return DownloadResult(success=False, route="failed", error="no OA URL known")

    download_dir.mkdir(parents=True, exist_ok=True)
    last_error: str | None = None

    for url in candidates:
        label = _route_label(url, meta)
        try:
            result = _try_one(url, meta, download_dir, label)
            if result.success:
                return result
            last_error = result.error
        except requests.RequestException as e:
            last_error = f"{type(e).__name__}: {e}"
            logger.debug("Route A request failed for %s: %s", url, e)

    return DownloadResult(success=False, route="failed", error=last_error or "all candidates failed")


def _try_one(url: str, meta: PaperMetadata, download_dir: Path, route: str) -> DownloadResult:
    logger.info("Route A trying %s", url)
    with requests.get(url, headers=_HEADERS, stream=True, timeout=60, allow_redirects=True) as r:
        if r.status_code >= 400:
            return DownloadResult(
                success=False,
                route=route,
                error=f"HTTP {r.status_code} from {url}",
            )

        ct = (r.headers.get("content-type") or "").lower()
        # First chunk must carry the %PDF- marker, regardless of what the server claims.
        first_chunk: bytes = b""
        for first_chunk in r.iter_content(chunk_size=_CHUNK):
            break
        if not first_chunk:
            return DownloadResult(success=False, route=route, error=f"empty body from {url}")
        if not _is_pdf_head(first_chunk):
            preview = first_chunk[:40].replace(b"\n", b" ")
            return DownloadResult(
                success=False,
                route=route,
                error=f"not a PDF (content-type={ct!r}, head={preview!r})",
            )

        target = download_dir / f"{meta.slug}.pdf"
        bytes_written = 0
        with open(target, "wb") as fh:
            fh.write(first_chunk)
            bytes_written += len(first_chunk)
            for chunk in r.iter_content(chunk_size=_CHUNK):
                if not chunk:
                    continue
                fh.write(chunk)
                bytes_written += len(chunk)
                if bytes_written > _MAX_BYTES:
                    fh.close()
                    target.unlink(missing_ok=True)
                    return DownloadResult(
                        success=False,
                        route=route,
                        error=f"PDF exceeds {_MAX_BYTES} bytes limit",
                    )

    logger.info("Route A saved %s (%d bytes)", target, bytes_written)
    return DownloadResult(success=True, path=target, route=route)


def write_pdf_bytes(data: bytes, meta: PaperMetadata, download_dir: Path) -> Path:
    """Helper used by Route B when it already has PDF bytes in memory."""
    download_dir.mkdir(parents=True, exist_ok=True)
    if not _is_pdf_head(data[:1024]):
        raise ValueError("bytes do not start with %PDF- signature")
    target = download_dir / f"{meta.slug}.pdf"
    target.write_bytes(data)
    return target
