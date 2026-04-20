"""End-to-end orchestration.

The pipeline is deliberately linear and verbose — the tricky parts live in
the modules it glues together, and failure at any step should still leave
useful partial state (a Zotero item tagged `needs-pdf`, a cached PDF path,
etc.) rather than lose work.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import replace

import questionary
from rich.console import Console
from rich.table import Table

from paper_fetch.cache import Cache
from paper_fetch.config import Settings
from paper_fetch.download import direct as direct_download
from paper_fetch.models import DownloadResult, PaperMetadata
from paper_fetch.search.crossref import CrossRef
from paper_fetch.search.semantic_scholar import SemanticScholar
from paper_fetch.search.unpaywall import Unpaywall
from paper_fetch.zotero_client import ZoteroClient

logger = logging.getLogger(__name__)
console = Console()


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------
async def run_pipeline(
    query: str | None,
    *,
    settings: Settings,
    smart: bool = False,
    use_vpn: bool = True,
    top_n: int = 5,
    dry_run: bool = False,
    doi: str | None = None,
) -> None:
    """Fetch a paper end-to-end, persisting partial progress at each step."""
    cache = Cache(settings.cache_dir)
    s2 = SemanticScholar(settings.s2_api_key, cache=cache)
    unpaywall = Unpaywall(settings.unpaywall_email, cache=cache)
    crossref = CrossRef(settings.unpaywall_email, cache=cache)

    # --- Phase 2: find the paper -------------------------------------------
    paper: PaperMetadata | None
    if doi:
        paper = s2.by_doi(doi) or crossref.by_doi(doi)
        if paper is None:
            console.print(f"[red]No metadata found for DOI {doi}[/]")
            return
    else:
        assert query is not None
        if smart:
            from paper_fetch.llm import rewrite_query

            sq = rewrite_query(query, model=settings.llm_model, api_key=settings.llm_api_key)
            results = s2.search(sq.boolean_query, limit=top_n)
        else:
            results = s2.search(query, limit=top_n)
        if not results:
            console.print("[red]No results from Semantic Scholar.[/]")
            return
        paper = _pick(results, top_n)
        if paper is None:
            console.print("[yellow]No paper selected, aborting.[/]")
            return

    # --- Enrich with Unpaywall when possible -------------------------------
    if paper.doi and not paper.unpaywall_pdf_url:
        url = unpaywall.lookup(paper.doi)
        if url:
            paper = replace(paper, unpaywall_pdf_url=url)
            logger.info("Unpaywall found OA PDF for %s", paper.doi)

    # --- Render metadata ---------------------------------------------------
    _render_metadata(paper)

    if dry_run:
        return

    # --- Phase 3: Route A --------------------------------------------------
    result: DownloadResult = direct_download.download(paper, settings.download_dir)

    # --- Phase 4: Route B --------------------------------------------------
    if not result.success and use_vpn:
        console.print("[yellow]Route A failed; attempting WebVPN…[/]")
        from paper_fetch.download import vpn

        result = await vpn.download(paper, settings)
    elif not result.success and not use_vpn:
        console.print("[yellow]Route A failed and --no-vpn set; skipping VPN path.[/]")

    # --- Cache PDF path for retry-failed -----------------------------------
    if result.success and result.path and paper.doi:
        cache.set(Cache.pdf_key(paper.doi), str(result.path))

    # --- Phase 5: Zotero upsert + attach -----------------------------------
    zclient = ZoteroClient(
        library_id=settings.zotero_user_id,
        library_type=settings.zotero_library_type,
        api_key=settings.zotero_api_key,
    )
    item_key = zclient.upsert_item(
        paper,
        tags=["needs-pdf"] if not result.success else None,
    )
    if result.success and result.path:
        try:
            zclient.attach_pdf(item_key, result.path)
        except Exception as e:
            logger.error("Zotero attach_pdf failed: %s", e)
            # PDF is still on disk; user can re-attach manually.
    _render_summary(paper, result, item_key)


async def run_retry_failed(settings: Settings) -> None:
    """Re-attempt Route B for every Zotero item tagged `needs-pdf`."""
    from paper_fetch.download import vpn

    cache = Cache(settings.cache_dir)
    zclient = ZoteroClient(
        library_id=settings.zotero_user_id,
        library_type=settings.zotero_library_type,
        api_key=settings.zotero_api_key,
    )
    items = zclient.items_needing_pdf()
    if not items:
        console.print("[green]No items tagged 'needs-pdf'.[/]")
        return

    for item in items:
        data = item.get("data", {})
        doi = data.get("DOI") or ""
        title = data.get("title") or "(untitled)"
        key = item.get("key") or ""
        if not doi:
            console.print(f"[yellow]Skipping {title!r} — no DOI.[/]")
            continue

        console.print(f"[cyan]Retrying: {title}[/]")
        meta = PaperMetadata(
            title=title,
            authors=[c.get("name") or f"{c.get('firstName','')} {c.get('lastName','')}".strip()
                     for c in data.get("creators") or []],
            doi=doi,
        )
        result = await vpn.download(meta, settings)
        if result.success and result.path:
            try:
                zclient.attach_pdf(key, result.path)
                zclient.remove_tag(key, "needs-pdf")
                cache.set(Cache.pdf_key(doi), str(result.path))
                console.print(f"[green]✓ {title}[/]")
            except Exception as e:
                console.print(f"[red]Attach failed for {title}: {e}[/]")
        else:
            console.print(f"[red]✗ {title} ({result.error})[/]")


# ---------------------------------------------------------------------------
# Presentation helpers
# ---------------------------------------------------------------------------
def _pick(results: list[PaperMetadata], top_n: int) -> PaperMetadata | None:
    if top_n <= 1 or len(results) == 1 or not sys.stdout.isatty():
        return results[0]
    choices = []
    for i, r in enumerate(results):
        first_author = r.authors[0] if r.authors else "—"
        year = r.year or "—"
        label = f"[{year}] {r.title} — {first_author}"
        if r.venue:
            label += f" ({r.venue})"
        choices.append(questionary.Choice(title=label, value=i))
    idx = questionary.select("Pick a paper:", choices=choices).ask()
    if idx is None:
        return None
    return results[idx]


def _render_metadata(paper: PaperMetadata) -> None:
    table = Table(title="Paper", show_header=False, box=None)
    table.add_row("Title", paper.title)
    table.add_row("Authors", ", ".join(paper.authors) or "—")
    table.add_row("Year", str(paper.year) if paper.year else "—")
    table.add_row("Venue", paper.venue or "—")
    table.add_row("DOI", paper.doi or "—")
    table.add_row("arXiv", paper.arxiv_id or "—")
    if paper.open_access_pdf_url:
        table.add_row("S2 OA PDF", paper.open_access_pdf_url)
    if paper.unpaywall_pdf_url:
        table.add_row("Unpaywall PDF", paper.unpaywall_pdf_url)
    console.print(table)


def _render_summary(paper: PaperMetadata, result: DownloadResult, item_key: str) -> None:
    if result.success:
        console.print(
            f"[green]✓ Zotero item {item_key} created/updated with PDF "
            f"(route={result.route}, publisher={result.publisher or '—'}).[/]"
        )
    else:
        console.print(
            f"[yellow]Created Zotero item {item_key} without PDF (tagged 'needs-pdf'). "
            f"Reason: {result.error}[/]"
        )
