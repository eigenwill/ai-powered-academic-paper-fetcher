"""Pydantic-settings-powered configuration.

Precedence: explicit constructor args > env vars > `.env` file > defaults.
Validation happens at startup so a misconfigured environment fails loudly
in `paper-fetch init`, not during the first outbound API call.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Zotero ---
    zotero_api_key: str = Field(..., description="Zotero API key")
    zotero_user_id: str = Field(..., description="Zotero user or group ID")
    zotero_library_type: str = Field("user", description="'user' or 'group'")

    # --- LLM ---
    llm_model: str = Field("gemini/gemini-2.0-flash", description="litellm model string")
    llm_api_key: str | None = None

    # --- Search providers ---
    s2_api_key: str | None = None
    unpaywall_email: str = Field(..., description="Email for Unpaywall API (required)")

    # --- Paths ---
    data_dir: Path = Field(default_factory=lambda: Path.home() / ".paper-fetch")
    playwright_user_data_dir: Path = Field(
        default_factory=lambda: Path.home() / ".paper-fetch" / "chromium-profile"
    )
    cache_dir: Path = Field(default_factory=lambda: Path.home() / ".paper-fetch" / "cache")
    download_dir: Path = Field(default_factory=lambda: Path.home() / ".paper-fetch" / "downloads")

    # --- WebVPN ---
    webvpn_base: str = "https://webvpn.fudan.edu.cn"

    # --- Optional: translation-server ---
    use_translation_server: bool = False
    translation_server_url: str = "http://localhost:1969"

    def ensure_dirs(self) -> None:
        """Create every path-typed setting if it doesn't already exist."""
        for p in (self.data_dir, self.cache_dir, self.download_dir, self.playwright_user_data_dir):
            p.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    """Lazy accessor — defers validation so tests can monkeypatch env vars."""
    return Settings()  # type: ignore[call-arg]
