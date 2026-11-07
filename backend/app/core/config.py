"""Environment-driven settings. No secrets are logged or returned by any API."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _b(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://quoteiq:quoteiq@localhost:5432/quoteiq"))
    anthropic_api_key: str | None = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY") or None)
    # Model IDs are configuration, not code. Override with ANTHROPIC_MODEL.
    anthropic_model: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5"))
    anthropic_api_url: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_URL", "https://api.anthropic.com"))
    base_currency: str = field(default_factory=lambda: os.environ.get("BASE_CURRENCY", "INR"))
    storage_path: Path = field(default_factory=lambda: Path(os.environ.get("STORAGE_PATH", "./storage")))
    max_upload_mb: float = field(default_factory=lambda: _f("MAX_UPLOAD_SIZE_MB", 25))
    # Heuristic confidence bands (0-100). Not calibrated probabilities.
    confidence_high: float = field(default_factory=lambda: _f("CONFIDENCE_HIGH", 90))
    confidence_review: float = field(default_factory=lambda: _f("CONFIDENCE_REVIEW_BELOW", 70))
    # Normalization policy (all disclosed in every calculation trace)
    compare_ex_tax: bool = field(default_factory=lambda: _b("COMPARE_EX_TAX", True))
    apply_early_payment_discounts: bool = field(default_factory=lambda: _b("APPLY_EARLY_PAYMENT_DISCOUNTS", False))
    freight_at_actuals_assumed_pct: float = field(default_factory=lambda: _f("FREIGHT_AT_ACTUALS_ASSUMED_PCT", 4.0))
    derived_weight_requires_review: bool = field(default_factory=lambda: _b("DERIVED_WEIGHT_REQUIRES_REVIEW", True))
    jwt_secret: str = field(default_factory=lambda: os.environ.get("JWT_SECRET", "dev-only-change-me"))

    def __post_init__(self):
        for prefix in ("postgres://", "postgresql://"):
            if self.database_url.startswith(prefix):
                self.database_url = "postgresql+psycopg://" + self.database_url[len(prefix):]
                break

    @property
    def ai_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
