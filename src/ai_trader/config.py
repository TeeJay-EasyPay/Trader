from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .models import AutoTradeConfig, GuardrailConfig


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    return default if value is None else float(value)


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value is None else int(value)


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class Settings:
    alpaca_api_key: str | None
    alpaca_secret_key: str | None
    alpaca_paper_base_url: str
    alpaca_data_base_url: str
    openai_api_key: str | None
    openai_model: str
    db_path: Path
    output_dir: Path
    trading_log_path: Path
    guardrails: GuardrailConfig
    auto_trade: AutoTradeConfig = field(default_factory=AutoTradeConfig)
    research_scheduler_enabled: bool = False
    research_scheduler_interval_minutes: int = 60
    research_scheduler_limit: int = 30

    @property
    def has_alpaca_credentials(self) -> bool:
        return bool(self.alpaca_api_key and self.alpaca_secret_key)


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        alpaca_api_key=os.getenv("ALPACA_API_KEY"),
        alpaca_secret_key=os.getenv("ALPACA_SECRET_KEY"),
        alpaca_paper_base_url=os.getenv("ALPACA_PAPER_BASE_URL", "https://paper-api.alpaca.markets"),
        alpaca_data_base_url=os.getenv("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        db_path=Path(os.getenv("AI_TRADER_DB_PATH", "data/audit.sqlite3")),
        output_dir=Path(os.getenv("AI_TRADER_OUTPUT_DIR", "data")),
        trading_log_path=Path(os.getenv("AI_TRADER_TRADING_LOG_PATH", "governance/TRADING_LOG.md")),
        guardrails=GuardrailConfig(
            max_risk_per_trade_pct=_float_env("MAX_RISK_PER_TRADE_PCT", 0.01),
            max_daily_loss_pct=_float_env("MAX_DAILY_LOSS_PCT", 0.03),
            max_open_positions=_int_env("MAX_OPEN_POSITIONS", 3),
            min_confidence_score=_float_env("MIN_CONFIDENCE_SCORE", 0.65),
            paper_trading_only=_bool_env("PAPER_TRADING_ONLY", True),
            allow_short_selling=_bool_env("ALLOW_SHORT_SELLING", False),
        ),
        auto_trade=AutoTradeConfig(
            enabled=_bool_env("AUTO_PAPER_TRADING", False),
            min_confidence=_float_env("AUTO_TRADE_MIN_CONFIDENCE", 0.85),
            min_philosophy_fit=_float_env("AUTO_TRADE_MIN_PHILOSOPHY_FIT", 0.85),
            max_trade_amount=_float_env("MAX_AUTO_TRADE_AMOUNT", 25.0),
            default_stop_loss_pct=_float_env("DEFAULT_STOP_LOSS_PCT", 0.03),
            max_stop_loss_pct=_float_env("MAX_STOP_LOSS_PCT", 0.05),
            crypto_max_trade_amount=_float_env("CRYPTO_MAX_AUTO_TRADE_AMOUNT", 10.0),
            crypto_default_stop_loss_pct=_float_env("CRYPTO_DEFAULT_STOP_LOSS_PCT", 0.02),
            crypto_max_stop_loss_pct=_float_env("CRYPTO_MAX_STOP_LOSS_PCT", 0.05),
        ),
        research_scheduler_enabled=_bool_env("RESEARCH_SCHEDULER_ENABLED", False),
        research_scheduler_interval_minutes=_int_env("RESEARCH_SCHEDULER_INTERVAL_MINUTES", 60),
        research_scheduler_limit=_int_env("RESEARCH_SCHEDULER_LIMIT", 30),
    )
