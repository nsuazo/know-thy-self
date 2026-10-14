"""Runtime configuration, read once from environment variables."""
import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", "/data")))
    tz: str = field(default_factory=lambda: _env("TZ", "America/Chicago"))
    # Writing before this hour counts toward the previous day.
    day_cutoff_hour: int = field(default_factory=lambda: _env_int("DAY_CUTOFF_HOUR", 4))
    # Local hour for the nightly Markdown export. -1 disables it.
    export_hour: int = field(default_factory=lambda: _env_int("EXPORT_HOUR", 3))

    # LLM settings (used from Phase 2 on).
    llm_base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL", "http://192.168.1.80:8090/v1"))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "gemma-official"))
    llm_timeout: int = field(default_factory=lambda: _env_int("LLM_TIMEOUT", 600))
    llm_max_tokens: int = field(default_factory=lambda: _env_int("LLM_MAX_TOKENS", 16384))
    context_budget_tokens: int = field(default_factory=lambda: _env_int("CONTEXT_BUDGET_TOKENS", 90000))
    # Thinking is on by default on the server. Set false to send enable_thinking=false per request
    # (verify with scripts/test_llm.py first).
    llm_enable_thinking: bool = field(
        default_factory=lambda: _env("LLM_ENABLE_THINKING", "true").strip().lower() in ("1", "true", "yes", "on")
    )
    # Entries from at least this many recent days are always included verbatim.
    context_min_days: int = field(default_factory=lambda: _env_int("CONTEXT_MIN_DAYS", 14))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "know-thy-self.db"

    @property
    def export_dir(self) -> Path:
        return self.data_dir / "export"


settings = Settings()
