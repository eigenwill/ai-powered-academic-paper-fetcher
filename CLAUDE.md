# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`paper-fetch` is a Python CLI tool that turns natural-language academic paper queries into Zotero library entries with attached PDFs. It routes through free/open-access sources first (arXiv, Unpaywall, Semantic Scholar), then falls back to Playwright-based browser automation through a WebVPN portal for paywalled publishers.

## Development Commands

All commands use `uv` (Astral's fast Python package manager):

```bash
uv sync --extra dev                 # Install all dependencies (including dev tools)
uv run playwright install chromium  # Install headless browser (one-time)

uv run pytest                       # Run all tests
uv run pytest tests/test_models.py  # Run a single test file
uv run pytest -k "test_name"        # Run a single test by name
RUN_VPN_TESTS=1 uv run pytest       # Include VPN integration tests (slow)

uv run ruff check .                 # Lint
uv run ruff check --fix .           # Lint and auto-fix
uv run mypy src/                    # Type check
```

## Architecture

The system is a **linear pipeline** in `pipeline.py` (`run_pipeline()`). Each phase produces partial state even on failure, so metadata always lands in Zotero even if the PDF fetch fails (tagged `needs-pdf`).

**Data flow:**

```
CLI (cli.py) → run_pipeline() (pipeline.py)
  Phase 1: Parse input (query string or --doi)
  Phase 2: Metadata lookup
    - Search:  SemanticScholar.search() + optional LLM rewrite (--smart)
    - By DOI:  S2.by_doi() → CrossRef.by_doi() fallback
    - Interactive picker (questionary) if TTY and top_n > 1
  Phase 3: Enrich with Unpaywall OA PDF URL
  Phase 4: Route A — direct HTTP download
    - Tries: Unpaywall URL → S2 OA URL → arXiv URL (in order)
    - Validates PDF magic bytes (%PDF-)
  Phase 5: Route B — VPN browser download (if Route A failed)
    - Persistent Chromium profile (playwright-stealth anti-detection)
    - Translates canonical DOI URL through WebVPN portal
    - Publisher adapters: Springer, Wiley, Elsevier, IEEE, ACS, Generic fallback
    - Dual PDF capture: expect_download() + response interception
  Phase 6: Cache PDF path (enables retry-failed command)
  Phase 7: Zotero upsert + attach PDF
    - DOI-based dedup (update existing vs. create new)
    - Tags item "needs-pdf" if no PDF was obtained
```

**Key modules:**
- `src/paper_fetch/config.py` — Pydantic Settings; all env vars loaded here
- `src/paper_fetch/models.py` — `PaperMetadata` (shared DTO) and `DownloadResult`
- `src/paper_fetch/pipeline.py` — main orchestration logic
- `src/paper_fetch/cli.py` — Typer CLI; thin wrappers around pipeline
- `src/paper_fetch/zotero_client.py` — pyzotero wrapper; item build, dedup, attach
- `src/paper_fetch/search/` — `semantic_scholar.py`, `unpaywall.py`, `crossref.py`
- `src/paper_fetch/download/direct.py` — Route A (HTTP streaming)
- `src/paper_fetch/download/vpn.py` — Route B (Playwright session + URL translation)
- `src/paper_fetch/download/adapters/` — Per-publisher PDF locators; `base.py` defines the protocol
- `src/paper_fetch/cache.py` — diskcache wrapper (S2: 7d TTL, Unpaywall/CrossRef: 30d, PDF paths: indefinite)
- `src/paper_fetch/llm.py` — optional litellm query rewriter (structured JSON output)

## Configuration

The app loads from a `.env` file (Pydantic Settings, case-insensitive). Required keys:

```
ZOTERO_API_KEY=
ZOTERO_USER_ID=
UNPAYWALL_EMAIL=
```

Optional keys:
```
ZOTERO_LIBRARY_TYPE=user           # 'user' or 'group'
S2_API_KEY=                        # Raises S2 rate limits
LLM_MODEL=gemini/gemini-2.0-flash  # litellm model string
LLM_API_KEY=
WEBVPN_BASE=https://webvpn.fudan.edu.cn
USE_TRANSLATION_SERVER=false
TRANSLATION_SERVER_URL=http://localhost:1969
```

Data/cache directories default to `~/.paper-fetch/` and are auto-created.

## Testing

- `conftest.py` provides an `_isolated_env` autouse fixture that redirects all data paths to temp dirs.
- `sample_meta` fixture provides a canonical test paper (Attention Is All You Need).
- VPN tests are guarded by `RUN_VPN_TESTS=1` env var since they require a live browser + credentials.

## Adding a Publisher Adapter

1. Create `src/paper_fetch/download/adapters/<publisher>.py` implementing the `PDFAdapter` protocol from `base.py`.
2. Register it in `vpn.py`'s adapter selection logic.
