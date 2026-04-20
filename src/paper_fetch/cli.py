"""Typer-powered CLI.

All commands are kept thin — the heavy lifting lives in the pipeline and
downstream modules. Each command only has to (a) resolve Settings, (b)
configure logging, and (c) call into one orchestration function.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from paper_fetch import __version__
from paper_fetch.logging_setup import configure_logging

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=f"AI-powered academic paper fetcher (v{__version__})",
)
console = Console()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Global option callbacks
# ---------------------------------------------------------------------------
@app.callback()
def main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable DEBUG logging."),
) -> None:
    configure_logging(verbose=verbose)


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------
@app.command()
def init() -> None:
    """Validate configuration and ping the Zotero API."""
    from paper_fetch.config import load_settings

    try:
        settings = load_settings()
    except Exception as e:
        console.print(f"[red]Configuration error:[/] {e}")
        raise typer.Exit(code=1)

    settings.ensure_dirs()

    # Ping Zotero — fails loud here, not mid-pipeline.
    from paper_fetch.zotero_client import ZoteroClient

    try:
        zc = ZoteroClient(
            library_id=settings.zotero_user_id,
            library_type=settings.zotero_library_type,
            api_key=settings.zotero_api_key,
        )
        zc.ping()
    except Exception as e:
        console.print(f"[red]Zotero ping failed:[/] {e}")
        raise typer.Exit(code=2)

    table = Table(title="paper-fetch config", show_header=False, box=None)
    table.add_row("Zotero library", f"{settings.zotero_library_type}/{settings.zotero_user_id}")
    table.add_row("LLM model", settings.llm_model)
    table.add_row("S2 API key", "present" if settings.s2_api_key else "unset (rate-limited)")
    table.add_row("Unpaywall email", settings.unpaywall_email)
    table.add_row("WebVPN", settings.webvpn_base)
    table.add_row("Data dir", str(settings.data_dir))
    table.add_row("Cache dir", str(settings.cache_dir))
    table.add_row("Download dir", str(settings.download_dir))
    console.print(table)
    console.print("[green][OK] Configuration valid.[/]")


# ---------------------------------------------------------------------------
# login / reset-session
# ---------------------------------------------------------------------------
@app.command()
def login() -> None:
    """Open a browser window to complete WebVPN login (one-time per session cookie lifetime)."""
    from paper_fetch.config import load_settings
    from paper_fetch.download import vpn

    settings = load_settings()
    settings.ensure_dirs()
    asyncio.run(vpn.login(settings))
    console.print("[green]Login window closed. Subsequent `get` calls will reuse this profile.[/]")


@app.command("reset-session")
def reset_session() -> None:
    """Delete the cached Chromium profile so the next `login` starts fresh."""
    from paper_fetch.config import load_settings
    from paper_fetch.download import vpn

    settings = load_settings()
    vpn.reset_session(settings)
    console.print("[green]Session wiped. Run `paper-fetch login` to re-authenticate.[/]")


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------
@app.command()
def get(
    query: Optional[str] = typer.Argument(None, help="Natural-language search query."),
    doi: Optional[str] = typer.Option(None, "--doi", help="Fetch a specific DOI directly."),
    top_n: int = typer.Option(5, "--top-n", "-n", help="How many S2 hits to surface."),
    smart: bool = typer.Option(
        False, "--smart", help="Rewrite the query with the configured LLM (off by default)."
    ),
    no_vpn: bool = typer.Option(
        False, "--no-vpn", help="Skip Route B even if Route A fails (metadata-only entry)."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Resolve metadata and print, but don't download or push to Zotero."
    ),
) -> None:
    """Search → pick → download → push to Zotero."""
    if not query and not doi:
        console.print("[red]Provide a query or --doi[/]")
        raise typer.Exit(code=1)

    from paper_fetch.config import load_settings
    from paper_fetch.pipeline import run_pipeline

    settings = load_settings()
    settings.ensure_dirs()

    try:
        asyncio.run(
            run_pipeline(
                query,
                settings=settings,
                smart=smart,
                use_vpn=not no_vpn,
                top_n=top_n,
                dry_run=dry_run,
                doi=doi,
            )
        )
    except KeyboardInterrupt:
        console.print("[yellow]Cancelled.[/]")
        raise typer.Exit(code=130)


# ---------------------------------------------------------------------------
# retry-failed
# ---------------------------------------------------------------------------
@app.command("retry-failed")
def retry_failed() -> None:
    """Re-run the VPN route for every Zotero item tagged 'needs-pdf'."""
    from paper_fetch.config import load_settings
    from paper_fetch.pipeline import run_retry_failed

    settings = load_settings()
    settings.ensure_dirs()
    asyncio.run(run_retry_failed(settings))


# ---------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------
cache_app = typer.Typer(help="Local cache management.")
app.add_typer(cache_app, name="cache")


@cache_app.command("clear")
def cache_clear() -> None:
    """Wipe the on-disk cache (S2, Unpaywall, PDF path index)."""
    from paper_fetch.cache import Cache
    from paper_fetch.config import load_settings

    settings = load_settings()
    cache = Cache(settings.cache_dir)
    removed = cache.clear()
    console.print(f"[green]Cleared {removed} entries from {settings.cache_dir}.[/]")


if __name__ == "__main__":
    app()
