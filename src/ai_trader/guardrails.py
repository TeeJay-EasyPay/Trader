from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .models import AccountContext, GuardrailConfig, TradeProposal, ValidationResult


def validate_trade_proposal(
    proposal: TradeProposal,
    account: AccountContext,
    config: GuardrailConfig,
    *,
    now: datetime | None = None,
) -> ValidationResult:
    p = proposal.normalized()
    failures: list[str] = []

    if config.paper_trading_only and p.asset_type != "crypto" and not account.is_paper:
        failures.append("paper_trading_only_failed")

    if p.side not in {"buy", "sell"}:
        failures.append("invalid_side")

    if p.position_size <= 0:
        failures.append("position_size_must_be_positive")

    if p.entry_price <= 0:
        failures.append("entry_price_must_be_positive")

    if p.stop_loss <= 0:
        failures.append("stop_loss_mandatory")

    if p.take_profit <= 0:
        failures.append("take_profit_mandatory")

    if p.confidence_score < config.min_confidence_score:
        failures.append("confidence_below_minimum")

    if account.equity <= 0:
        failures.append("account_equity_must_be_positive")
    else:
        max_trade_risk = account.equity * config.max_risk_per_trade_pct
        proposal_risk = abs(p.entry_price - p.stop_loss) * p.position_size
        if proposal_risk <= 0:
            failures.append("risk_must_be_positive")
        if proposal_risk > max_trade_risk:
            failures.append("max_account_risk_per_trade_exceeded")

        if p.risk_percentage > config.max_risk_per_trade_pct:
            failures.append("declared_risk_percentage_exceeded")

        max_daily_loss = account.equity * config.max_daily_loss_pct
        if account.daily_realized_pnl <= -max_daily_loss:
            failures.append("maximum_daily_loss_exceeded")

    if len(account.open_positions) >= config.max_open_positions:
        failures.append("maximum_open_positions_exceeded")

    existing_symbols = {position.symbol.upper() for position in account.open_positions}
    has_existing_position = p.symbol in existing_symbols
    if p.side == "buy" and has_existing_position:
        failures.append("duplicate_open_position")
    if p.side == "sell" and not has_existing_position and not config.allow_short_selling:
        failures.append("short_selling_disabled")

    if p.side == "buy":
        if p.stop_loss >= p.entry_price:
            failures.append("buy_stop_loss_must_be_below_entry")
        if p.take_profit <= p.entry_price:
            failures.append("buy_take_profit_must_be_above_entry")
    if p.side == "sell":
        if p.stop_loss <= p.entry_price:
            failures.append("sell_stop_loss_must_be_above_entry")
        if p.take_profit >= p.entry_price:
            failures.append("sell_take_profit_must_be_below_entry")

    if p.asset_type not in {"crypto"} and not is_us_equity_trading_hours(now):
        failures.append("outside_regular_trading_hours")

    return ValidationResult(passed=not failures, failures=failures)


def is_us_equity_trading_hours(now: datetime | None = None) -> bool:
    current = now or datetime.now(tz=ZoneInfo("UTC"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo("UTC"))
    eastern = current.astimezone(ZoneInfo("America/New_York"))
    if eastern.weekday() >= 5:
        return False
    market_open = eastern.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = eastern.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= eastern <= market_close

