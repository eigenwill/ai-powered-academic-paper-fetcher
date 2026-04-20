# paper-fetch

Turn a natural-language query (or a bare DOI) into a Zotero library entry with the PDF attached — fully automated.

The tool tries free/open-access sources first (arXiv, Unpaywall, Semantic Scholar). If the paper is paywalled, it falls back to Playwright-driven browser automation through a WebVPN portal (default: Fudan University) and a set of publisher-specific adapters for Springer, Wiley, Elsevier, IEEE, and ACS.

---

## Requirements

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) — fast Python package manager
- A [Zotero](https://www.zotero.org/) account with a library you can write to
- Access to a WebVPN portal **only** if you need paywalled PDFs

---

## Installation

```bash
# 1. Install uv (skip if already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Clone and install dependencies
git clone https://github.com/eigenwill/ai-powered-academic-paper-fetcher.git
cd ai-powered-academic-paper-fetcher
uv sync --extra dev

# 3. Install the Chromium browser (for VPN-mediated downloads)
uv run playwright install chromium

# 4. Configure your credentials
cp .env.example .env
# Open .env and fill in at minimum: ZOTERO_API_KEY, ZOTERO_USER_ID, UNPAYWALL_EMAIL

# 5. Verify the setup
uv run paper-fetch init
```

---

## Configuration

All configuration is read from a `.env` file in the project root. Copy `.env.example` to get started.

### Required

| Variable | Description |
|---|---|
| `ZOTERO_API_KEY` | API key from [zotero.org/settings/keys](https://www.zotero.org/settings/keys) (needs read + write) |
| `ZOTERO_USER_ID` | Your Zotero user ID (shown on the same page) |
| `UNPAYWALL_EMAIL` | Any valid email — Unpaywall uses it for rate-limit identification |

### Optional

| Variable | Default | Description |
|---|---|---|
| `ZOTERO_LIBRARY_TYPE` | `user` | `user` or `group` |
| `S2_API_KEY` | — | Semantic Scholar key for higher rate limits ([request here](https://www.semanticscholar.org/product/api)) |
| `LLM_MODEL` | `gemini/gemini-2.0-flash` | Any [litellm](https://docs.litellm.ai/docs/providers) model string; only used with `--smart` |
| `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | — | API key matching your chosen `LLM_MODEL` provider |
| `WEBVPN_BASE` | `https://webvpn.fudan.edu.cn` | Base URL of your WebVPN portal |
| `USE_TRANSLATION_SERVER` | `false` | Route metadata through a local [Zotero Translation Server](https://github.com/zotero/translation-server) |
| `TRANSLATION_SERVER_URL` | `http://localhost:1969` | Translation server address |
| `DATA_DIR` | `~/.paper-fetch` | Root directory for all runtime data |
| `CACHE_DIR` | `~/.paper-fetch/cache` | Search and metadata cache |
| `DOWNLOAD_DIR` | `~/.paper-fetch/downloads` | Downloaded PDF storage |
| `PLAYWRIGHT_USER_DATA_DIR` | `~/.paper-fetch/chromium-profile` | Persistent Chromium profile (stores VPN session cookies) |

---

## Usage

### Basic search

```bash
# Natural-language query — shows an interactive picker (top 5 results)
uv run paper-fetch get "attention is all you need"

# Direct DOI lookup — bypasses search entirely
uv run paper-fetch get --doi 10.1038/nature14539

# Limit picker to top 3 results
uv run paper-fetch get "diffusion models beat GANs" --top-n 3
```

### Download control

```bash
# Skip VPN path; creates a metadata-only Zotero entry (tagged "needs-pdf") on paywall hit
uv run paper-fetch get "diffusion models" --no-vpn

# Preview resolved metadata without downloading or touching Zotero
uv run paper-fetch get "transformer attention" --dry-run

# Rewrite the query with an LLM before searching (useful for domain-heavy or ambiguous terms)
uv run paper-fetch get "silicon phototransistor noise mechanism" --smart
```

### VPN session management

```bash
# Open a browser window to log in to your WebVPN portal (one-time per machine)
uv run paper-fetch login

# Wipe the saved Chromium profile and start fresh (if your session is broken)
uv run paper-fetch reset-session
```

### Maintenance

```bash
# Re-attempt PDF downloads for all Zotero items tagged "needs-pdf"
uv run paper-fetch retry-failed

# Clear the local search, metadata, and PDF path cache
uv run paper-fetch cache clear

# Validate config and test Zotero connectivity
uv run paper-fetch init
```

### Verbose output

Add `-v` / `--verbose` to any command for DEBUG-level logging:

```bash
uv run paper-fetch get "BERT language model" -v
```

---

## How It Works

The `get` command runs a linear pipeline:

1. **Search** — Queries Semantic Scholar (S2). With `--smart`, rewrites the query via LLM first. Prompts you to pick from the top results interactively when running in a TTY.
2. **Enrich** — Looks up the selected paper's DOI in Unpaywall to find open-access PDF URLs.
3. **Route A — Direct download** — Tries Unpaywall URL → S2 OA URL → arXiv in order. Validates that the response is a real PDF (`%PDF-` magic bytes).
4. **Route B — VPN download** (if Route A fails and `--no-vpn` is not set) — Launches a persistent headless Chromium session, translates the canonical DOI URL through the WebVPN portal, and uses a publisher-specific adapter (Springer / Wiley / Elsevier / IEEE / ACS / Generic) to locate and capture the PDF.
5. **Zotero upsert** — Creates or updates the item (DOI-deduped) and attaches the PDF. If no PDF was obtained, tags the item `needs-pdf` so `retry-failed` can attempt it later.

Results and metadata are cached (S2 queries: 7 days; Unpaywall/CrossRef: 30 days) to avoid redundant API calls.

---

## Supported Publishers (VPN Route)

| Publisher | Adapter |
|---|---|
| Springer / SpringerLink | `download/adapters/springer.py` |
| Wiley Online Library | `download/adapters/wiley.py` |
| Elsevier / ScienceDirect | `download/adapters/elsevier.py` |
| IEEE Xplore | `download/adapters/ieee.py` |
| ACS Publications | `download/adapters/acs.py` |
| All others | `download/adapters/generic.py` (fallback) |

To add a new publisher, implement the `PDFAdapter` protocol in `download/adapters/base.py` and register it in `download/vpn.py`.

---

## Development

```bash
# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_pipeline.py

# Run a specific test by name
uv run pytest -k "test_route_a_happy_path"

# Include VPN integration tests (requires a live WebVPN session)
RUN_VPN_TESTS=1 uv run pytest

# Lint
uv run ruff check .
uv run ruff check --fix .

# Type check
uv run mypy src/
```

The test suite uses an `_isolated_env` autouse fixture that redirects all data paths to a temporary directory, so tests never touch `~/.paper-fetch`.

---

## Project Structure

```
src/paper_fetch/
├── cli.py               # Typer CLI entry point
├── pipeline.py          # Main orchestration (run_pipeline, run_retry_failed)
├── config.py            # Pydantic Settings — all env vars
├── models.py            # PaperMetadata, DownloadResult
├── zotero_client.py     # Zotero API wrapper (upsert, attach, tag)
├── cache.py             # diskcache wrapper with TTL helpers
├── llm.py               # Optional LLM query rewriter (litellm)
├── logging_setup.py     # Rich-backed logging
├── search/
│   ├── semantic_scholar.py
│   ├── unpaywall.py
│   └── crossref.py
└── download/
    ├── direct.py        # Route A — HTTP streaming
    ├── vpn.py           # Route B — Playwright + WebVPN
    └── adapters/        # Per-publisher PDF locators
        ├── base.py
        ├── springer.py
        ├── wiley.py
        ├── elsevier.py
        ├── ieee.py
        ├── acs.py
        └── generic.py
```

---

## License

MIT
