from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .models import AccountContext, GuardrailConfig, TradeProposal, ValidationResult


def validate_trade_proposal(
    proposal: TradeProposal,
    account: AccountContext,
    config: GuardrailConfig,
    *,
    now: datetime | None = None,
    ai_managed_symbols: set[str] | list[str] | None = None,
    max_open_positions: int | None = None,
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

    # 2026-09-01, P1 of the "one home per decision" work. This used to be one of TWO position
    # caps. The other lived in orchestrator.py, was per broker, and emitted a different name
    # (maximum_concurrent_positions_exceeded) -- so the same decision was checked twice against
    # two different numbers. Measured on live refusals: 34 hits here and 17 there, 51 of 77
    # refusals in total, all of them one rule counted twice.
    #
    # It is also why raising Alpaca's cap from 5 to 10 on 2026-08-31 did nothing. The per-broker
    # value said 10, this broker-blind one still said 5, and this one runs first.
    #
    # Now there is one check. `max_open_positions` is opt-in, exactly like `ai_managed_symbols`
    # above: a caller that knows which broker it is trading passes the per-broker cap, and a
    # caller that does not keeps the shared config value it always used. So the orchestrator
    # gets the correct number and no other path silently loses its cap.
    effective_max_open_positions = (
        config.max_open_positions if max_open_positions is None else int(max_open_positions)
    )
    if len(account.open_positions) >= effective_max_open_positions:
        failures.append("maximum_open_positions_exceeded")

    existing_symbols = {position.symbol.upper() for position in account.open_positions}
    has_existing_position = p.symbol in existing_symbols
    # 2026-08-25, Founder-directed. "Duplicate" for a BUY means this system already runs
    # its own open trade in the symbol -- not merely that the wallet contains the coin.
    #
    # Measured that morning: the Kraken wallet held 14 coins, of which only 3 were
    # AI-managed trades (BCH, GRT, AAVE). The other 11 are the Founder's own pre-existing
    # holdings, which this system did not open, does not manage and must not sell. Judging
    # duplicates by wallet contents therefore banned the AI from 14 of its 19 allowed
    # pairs, leaving it shopping in 5 -- which is why GRT was proposed and rejected seven
    # times in one night, and why two trades were placed in a full day. It was not short
    # of ideas; it had almost nowhere to put them.
    #
    # Passing ai_managed_symbols is opt-in: callers that do not know which trades are
    # AI-managed keep the old wallet-based behaviour exactly. The genuine risk controls
    # are untouched -- max_open_positions above, and the per-broker AI open-trade cap
    # upstream -- so this widens where the AI may look, not how much it may hold.
    #
    # SELLS deliberately still use the wallet: you can only sell what is actually there,
    # and that check has nothing to do with which system opened the position.
    duplicate_scope = existing_symbols if ai_managed_symbols is None else {
        str(symbol).upper() for symbol in ai_managed_symbols
    }
    if p.side == "buy" and p.symbol in duplicate_scope:
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


def us_equity_market_hours_between(start: datetime, end: datetime) -> timedelta:
    """How much US equity TRADING time separates two instants.

    2026-08-22: equity recommendations were expiring by wall clock. A high-confidence idea
    gets a 4-hour life, but the US market is shut ~73% of the week, so anything generated
    late in a session -- or at all overnight or at a weekend -- was dead before the next
    open and could never be acted on. Confirmed live: all 40 equity recommendations read
    "Expired. Run new analysis before execution." and Alpaca had not filled since 12 Aug.

    Ageing an equity idea only while its market is actually open is the honest measure:
    4 hours of life should mean 4 hours in which the trade could genuinely have been
    placed. Crypto is unaffected -- it trades continuously, so wall clock IS market time.

    Ignores exchange holidays (no holiday calendar exists in this codebase), which errs
    toward keeping a recommendation alive very slightly longer -- never toward acting on a
    stale one, since the trading-hours guardrail still blocks execution on a closed market.
    """
    if end <= start:
        return timedelta(0)
    # A span this long is expired under every lifetime the caller can supply; bounded so a
    # far-future or corrupt timestamp cannot spin this loop.
    if (end - start) > timedelta(days=30):
        return timedelta(days=30)
    eastern = ZoneInfo("America/New_York")
    begin = start.astimezone(eastern)
    finish = end.astimezone(eastern)
    total = timedelta(0)
    day = begin.date()
    while day <= finish.date():
        if day.weekday() < 5:
            session_open = datetime.combine(day, time(9, 30), tzinfo=eastern)
            session_close = datetime.combine(day, time(16, 0), tzinfo=eastern)
            overlap_start = max(begin, session_open)
            overlap_end = min(finish, session_close)
            if overlap_end > overlap_start:
                total += overlap_end - overlap_start
        day += timedelta(days=1)
    return total


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

