"""Route B: Fudan WebVPN-mediated Playwright download.

This is the fragile component; everything here is defensively structured so
a broken step ends with a clear `DownloadResult(success=False, error=...)`
instead of an exception that takes down the whole pipeline.

Key mechanisms:
- Persistent Chromium profile (cookies, SSO state) under `user_data_dir`.
- Session health check before each run.
- URL translation via a cached encoding scheme (Strategy B), falling back
  to the portal's address box (Strategy A).
- PDF retrieval via **two concurrent mechanisms**:
    1. `page.expect_download()` for `Content-Disposition: attachment`.
    2. `response` event interception for inline `application/pdf`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path

from paper_fetch.config import Settings
from paper_fetch.download.adapters import pick_adapter
from paper_fetch.download.direct import PDF_MAGIC, write_pdf_bytes
from paper_fetch.models import DownloadResult, PaperMetadata

logger = logging.getLogger(__name__)

_SELECTOR_STORE = "webvpn_selectors.json"
_URL_SCHEME_STORE = "webvpn_url_scheme.json"

_DEFAULT_LOGIN_SELECTORS = [
    # Common "logged-in" indicators — user may customize these during login.
    'a[href*="logout" i]',
    'button:has-text("Logout")',
    'button:has-text("退出")',
    'img[alt*="avatar" i]',
    '#user-info',
    '.user-avatar',
]


# ---------------------------------------------------------------------------
# Small persistent JSON helpers
# ---------------------------------------------------------------------------
def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Could not read %s: %s", path, e)
        return None


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------
async def login(settings: Settings) -> None:
    """Open a visible browser window so the user can complete CAS/SSO login."""
    from playwright.async_api import async_playwright

    settings.playwright_user_data_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(settings.playwright_user_data_dir),
            headless=False,
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(settings.webvpn_base)
        logger.info(
            "A browser window has opened. Log in through the portal, "
            "then close the window to finish."
        )
        try:
            await ctx.wait_for_event("close", timeout=0)
        except Exception:
            pass


def reset_session(settings: Settings) -> None:
    """Delete the persisted Chromium profile (cookies, session state)."""
    target = settings.playwright_user_data_dir
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
        logger.info("Deleted %s", target)


async def download(meta: PaperMetadata, settings: Settings) -> DownloadResult:
    """Main Route B entry point — called by the pipeline after Route A fails."""
    if not meta.canonical_url:
        return DownloadResult(success=False, route="failed", error="no canonical URL to navigate to")

    from playwright.async_api import async_playwright

    settings.playwright_user_data_dir.mkdir(parents=True, exist_ok=True)
    settings.download_dir.mkdir(parents=True, exist_ok=True)
    selectors_path = settings.data_dir / _SELECTOR_STORE
    scheme_path = settings.data_dir / _URL_SCHEME_STORE

    async with async_playwright() as p:
        try:
            ctx = await p.chromium.launch_persistent_context(
                user_data_dir=str(settings.playwright_user_data_dir),
                headless=True,
                accept_downloads=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception as e:
            return DownloadResult(success=False, route="failed", error=f"browser launch failed: {e}")

        try:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await _apply_stealth(page)

            # --- Session health check ---
            if not await _session_ok(page, settings, selectors_path):
                return DownloadResult(
                    success=False,
                    route="failed",
                    error="WebVPN session expired. Run `paper-fetch login` and retry.",
                )

            # --- URL translation ---
            target_url = await _translate_url(page, settings, meta.canonical_url, scheme_path)
            if not target_url:
                return DownloadResult(
                    success=False,
                    route="failed",
                    error="could not translate canonical URL through WebVPN",
                )

            # --- Navigate + extract ---
            try:
                await page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)
            except Exception as e:
                return DownloadResult(success=False, route="failed", error=f"goto failed: {e}")

            adapter = pick_adapter(page.url)
            logger.info("Using adapter: %s (url=%s)", adapter.name, page.url)

            try:
                await adapter.pre_click_hook(page)
            except Exception as e:
                logger.debug("pre_click_hook threw: %s", e)

            element = await adapter.locate_pdf_element(page)
            if element is None:
                await _dump_debug(page, settings, adapter.name)
                return DownloadResult(
                    success=False,
                    route="failed",
                    publisher=adapter.name,
                    error=f"adapter '{adapter.name}' could not find a PDF element",
                )

            result = await _click_and_capture(page, ctx, element, meta, settings, adapter.name)
            return result
        finally:
            await ctx.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _apply_stealth(page) -> None:
    try:
        from playwright_stealth import stealth_async  # type: ignore

        await stealth_async(page)
    except Exception as e:
        logger.debug("playwright-stealth unavailable: %s", e)


async def _session_ok(page, settings: Settings, selectors_path: Path) -> bool:
    try:
        await page.goto(settings.webvpn_base, wait_until="domcontentloaded", timeout=30_000)
    except Exception as e:
        logger.warning("WebVPN base unreachable: %s", e)
        return False

    stored = _load_json(selectors_path) or {}
    candidates = stored.get("logged_in_selectors") or _DEFAULT_LOGIN_SELECTORS
    for sel in candidates:
        try:
            el = await page.query_selector(sel)
            if el:
                return True
        except Exception:
            continue
    # If we landed on something that looks like the CAS login page, consider it expired.
    url = page.url.lower()
    if "login" in url or "cas" in url or "idp" in url:
        return False
    # Ambiguous: be optimistic rather than forcing an unnecessary re-login.
    return True


async def _translate_url(page, settings: Settings, canonical: str, scheme_path: Path) -> str | None:
    """Translate a canonical URL into a WebVPN-rewritten URL.

    Strategy B (preferred): apply a cached encoding template.
    Strategy A (fallback): submit the URL to the portal's address box.
    """
    scheme = _load_json(scheme_path) or {}

    # --- Strategy B ---
    template = scheme.get("template")  # e.g. "https://webvpn.fudan.edu.cn/{PROTO}/{PREFIX}/{PATH}"
    prefix = scheme.get("prefix")
    if template and prefix:
        try:
            proto, rest = canonical.split("://", 1)
            return (
                template.replace("{PROTO}", proto)
                .replace("{PREFIX}", prefix)
                .replace("{PATH}", rest)
            )
        except Exception as e:
            logger.debug("Strategy B template failed: %s", e)

    # --- Strategy A ---
    try:
        box = None
        for sel in ('input[type="text"]', 'input[name="url"]', 'input[placeholder*="URL" i]'):
            box = await page.query_selector(sel)
            if box:
                break
        if box is None:
            logger.warning("No URL input found on WebVPN portal.")
            return None
        await box.fill(canonical)
        # Most portals accept Enter to submit.
        await box.press("Enter")
        await page.wait_for_load_state("domcontentloaded", timeout=45_000)

        translated = page.url
        # Opportunistically learn the scheme for next time.
        if translated and translated.startswith(settings.webvpn_base):
            _maybe_learn_scheme(translated, canonical, settings, scheme_path)
        return translated
    except Exception as e:
        logger.warning("Strategy A failed: %s", e)
        return None


def _maybe_learn_scheme(translated: str, canonical: str, settings: Settings, scheme_path: Path) -> None:
    """Infer a `{PROTO}/{PREFIX}/{PATH}` template from one successful run.

    Fudan's Sangfor-based WebVPN rewrites URLs like
    ``https://doi.org/10.x/y`` to
    ``https://webvpn.fudan.edu.cn/https/<opaque-prefix>/doi.org/10.x/y``.
    Once we capture that opaque prefix, subsequent navigations skip the
    portal entirely.
    """
    try:
        proto, _rest = canonical.split("://", 1)
        after_base = translated[len(settings.webvpn_base):].lstrip("/")
        parts = after_base.split("/", 2)
        if len(parts) < 3 or parts[0] != proto:
            return
        prefix = parts[1]
        template = settings.webvpn_base.rstrip("/") + "/{PROTO}/{PREFIX}/{PATH}"
        _save_json(scheme_path, {"template": template, "prefix": prefix})
        logger.info("Learned WebVPN URL scheme: prefix=%s", prefix)
    except Exception as e:
        logger.debug("scheme learning skipped: %s", e)


async def _click_and_capture(page, ctx, element, meta, settings, publisher_name) -> DownloadResult:
    """Click the PDF element and race two PDF-capture mechanisms.

    Mechanism 1 — response interception: handles inline viewers that serve
    `application/pdf` in an iframe/embed.
    Mechanism 2 — `page.wait_for_event("download")`: handles publishers
    that send `Content-Disposition: attachment`.
    """
    pdf_bytes: list[bytes] = []

    async def on_response(response):
        try:
            ct = (response.headers.get("content-type") or "").lower()
            if "application/pdf" in ct and not pdf_bytes:
                body = await response.body()
                if body and PDF_MAGIC in body[:1024]:
                    pdf_bytes.append(body)
        except Exception as e:
            logger.debug("response handler error: %s", e)

    page.on("response", on_response)

    download_task = asyncio.create_task(
        page.wait_for_event("download", timeout=45_000)
    )

    try:
        # Click — publishers sometimes open a new tab; `popup` events bubble
        # up, so the download listener still fires on the browser context.
        try:
            await element.click(timeout=10_000)
        except Exception as e:
            logger.debug("primary click failed (%s), retrying without timeout", e)
            try:
                await element.click()
            except Exception as e2:
                return DownloadResult(
                    success=False,
                    route="failed",
                    publisher=publisher_name,
                    error=f"click failed: {e2}",
                )

        # Poll both mechanisms; first one to produce PDF bytes wins.
        for _ in range(60):  # up to 30 s
            if pdf_bytes:
                try:
                    path = write_pdf_bytes(pdf_bytes[0], meta, settings.download_dir)
                    return DownloadResult(
                        success=True, path=path, route="vpn", publisher=publisher_name
                    )
                except Exception as e:
                    return DownloadResult(
                        success=False,
                        route="failed",
                        publisher=publisher_name,
                        error=f"intercepted bytes invalid: {e}",
                    )
            if download_task.done():
                try:
                    download = download_task.result()
                except Exception:
                    break
                target = settings.download_dir / f"{meta.slug}.pdf"
                try:
                    await download.save_as(str(target))
                except Exception as e:
                    return DownloadResult(
                        success=False,
                        route="failed",
                        publisher=publisher_name,
                        error=f"download save failed: {e}",
                    )
                # Sanity-check magic bytes.
                try:
                    head = target.open("rb").read(1024)
                    if PDF_MAGIC not in head:
                        return DownloadResult(
                            success=False,
                            route="failed",
                            publisher=publisher_name,
                            error="download did not produce a PDF",
                        )
                except OSError as e:
                    return DownloadResult(
                        success=False,
                        route="failed",
                        publisher=publisher_name,
                        error=f"saved file unreadable: {e}",
                    )
                return DownloadResult(
                    success=True, path=target, route="vpn", publisher=publisher_name
                )
            await asyncio.sleep(0.5)

        return DownloadResult(
            success=False,
            route="failed",
            publisher=publisher_name,
            error="no PDF bytes captured within 30 s",
        )
    finally:
        if not download_task.done():
            download_task.cancel()
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass


async def _dump_debug(page, settings: Settings, label: str) -> None:
    try:
        target = settings.data_dir / "debug"
        target.mkdir(parents=True, exist_ok=True)
        html = await page.content()
        (target / f"{label}.html").write_text(html, encoding="utf-8")
        await page.screenshot(path=str(target / f"{label}.png"), full_page=True)
    except Exception as e:
        logger.debug("debug dump failed: %s", e)
