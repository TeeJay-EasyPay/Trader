from __future__ import annotations

import html
import logging
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from ..audit import AuditDatabase
from ..config import Settings
from ..database import connect
from ..models import utc_now_iso
from ..multi_broker import record_notification
from ..operational import safe_float
from ..persistence.query_executor import QueryExecutor
from ..persistence.schema_once import ensure_schema_once
from .shared_helpers import _broker_label, _broker_trade_payload, _broker_trade_symbol, _estimated_in_positions, _money_text

logger = logging.getLogger("ai_trader.api")

REPORT_SCHEMA = """
CREATE TABLE IF NOT EXISTS TRADING_REPORTS (
    report_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    report_date TEXT NOT NULL,
    broker TEXT NOT NULL,
    report_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    report_markdown TEXT NOT NULL,
    file_path TEXT
);
"""


# Phase 3 (architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md): these two
# helpers are pure, stateless formatting utilities also used by parts of api/__init__.py
# that are out of this phase's scope, so they cannot be moved without either reversing the
# api->application dependency direction or introducing an import-order-sensitive lazy
# import neither of which this codebase uses elsewhere. Duplicated verbatim here. The other
# five formatting helpers that used to be duplicated alongside these two were consolidated
# into shared_helpers.py in Phase 9 (see the import above) once every other duplicate site
# had also been extracted.
def _human_time(value: Any) -> str:
    if not value:
        return "Not available"
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%d %b %Y, %H:%M UTC")


def _list_or_none(items: list[str]) -> str:
    if not items:
        return "- None recorded"
    return "\n".join(item if str(item).startswith("- ") else f"- {item}" for item in items)


def _broker_trade_side(row: dict[str, Any]) -> str | None:
    payload = _broker_trade_payload(row)
    value = row.get("side") or payload.get("side") or payload.get("type")
    value = str(value).lower() if value else ""
    if value in {"buy", "sell"}:
        return value
    return None


def _broker_trade_quantity(row: dict[str, Any]) -> float | None:
    payload = _broker_trade_payload(row)
    return safe_float(row.get("quantity") or payload.get("qty") or payload.get("quantity") or payload.get("vol"))


def _broker_trade_price(row: dict[str, Any]) -> float | None:
    payload = _broker_trade_payload(row)
    return safe_float(row.get("price") or payload.get("price") or payload.get("filled_avg_price"))


def _broker_trade_time(row: dict[str, Any]) -> str | None:
    payload = _broker_trade_payload(row)
    return (
        row.get("closed_at")
        or row.get("opened_at")
        or payload.get("transaction_time")
        or payload.get("filled_at")
        or payload.get("created_at")
        or payload.get("time")
        or row.get("updated_at")
    )


def _first_markdown_bullet(markdown: str) -> str | None:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            return stripped[2:]
    return None


def _report_period(report_date: date, report_type: str) -> dict[str, str]:
    report_type = report_type.lower()
    if report_type == "morning":
        start_date = report_date - timedelta(days=1)
        start_dt = datetime(start_date.year, start_date.month, start_date.day, 16, 0, tzinfo=timezone.utc)
        end_dt = datetime(report_date.year, report_date.month, report_date.day, 9, 0, tzinfo=timezone.utc)
        label = "Morning report window: prior market close through 09:00 UTC"
    elif report_type == "evening":
        start_dt = datetime(report_date.year, report_date.month, report_date.day, 9, 0, tzinfo=timezone.utc)
        end_dt = datetime(report_date.year, report_date.month, report_date.day, 23, 59, 59, tzinfo=timezone.utc)
        label = "Evening report window: 09:00 UTC through end of day"
    elif report_type == "weekly":
        start_date = report_date - timedelta(days=report_date.weekday())
        end_date = start_date + timedelta(days=6)
        start_dt = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
        end_dt = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc)
        label = f"Weekly report window: ISO week starting {start_date.isoformat()}"
    elif report_type == "monthly":
        start_date = report_date.replace(day=1)
        if start_date.month == 12:
            next_month = start_date.replace(year=start_date.year + 1, month=1)
        else:
            next_month = start_date.replace(month=start_date.month + 1)
        end_date = next_month - timedelta(days=1)
        start_dt = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
        end_dt = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc)
        label = f"Monthly report window: {start_date.strftime('%B %Y')}"
    else:
        start_dt = datetime(report_date.year, report_date.month, report_date.day, tzinfo=timezone.utc)
        end_dt = datetime(report_date.year, report_date.month, report_date.day, 23, 59, 59, tzinfo=timezone.utc)
        label = "Daily report window: full calendar day UTC"
    return {"start": start_dt.isoformat(), "end": end_dt.isoformat(), "label": label}


def _balance_summary_by_broker(snapshots: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in snapshots:
        broker = str(row.get("broker") or row.get("exchange") or "unknown")
        grouped[broker].append(row)
    summary: dict[str, dict[str, Any]] = {}
    for broker, rows in grouped.items():
        ordered = sorted(rows, key=lambda item: item.get("created_at") or "")
        start = ordered[0]
        end = ordered[-1]
        start_balance = safe_float(start.get("portfolio_value"))
        end_balance = safe_float(end.get("portfolio_value"))
        start_cash = safe_float(start.get("cash"))
        end_cash = safe_float(end.get("cash"))
        balance_change = None if start_balance is None or end_balance is None else end_balance - start_balance
        summary[broker] = {
            "start": start,
            "end": end,
            "start_balance": start_balance,
            "end_balance": end_balance,
            "start_cash": start_cash,
            "end_cash": end_cash,
            "start_in_positions": _estimated_in_positions(start_balance, start_cash),
            "end_in_positions": _estimated_in_positions(end_balance, end_cash),
            "balance_change": balance_change,
            "snapshot_count": len(ordered),
        }
    return summary


def _balance_summary_lines(summary: dict[str, dict[str, Any]]) -> str:
    if not summary:
        return "- No start/end portfolio snapshots were available for this period."
    lines = []
    for broker, item in summary.items():
        lines.append(
            f"- {broker.title()}: start {_money_text(item.get('start_balance'))} at {_human_time(item['start'].get('created_at'))}; "
            f"end {_money_text(item.get('end_balance'))} at {_human_time(item['end'].get('created_at'))}; "
            f"cash {_money_text(item.get('end_cash'))}; estimated in positions {_money_text(item.get('end_in_positions'))}; "
            f"balance change {_money_text(item.get('balance_change'))}; snapshots {item.get('snapshot_count')}."
        )
    return "\n".join(lines)


def _performance_summary_lines(
    balance_summary: dict[str, dict[str, Any]],
    attribution: list[dict[str, Any]],
    broker_trades: list[dict[str, Any]],
    reconstructed: dict[str, Any],
) -> list[str]:
    lines = []
    total_closed_pnl = sum(safe_float(row.get("profit_loss")) or 0.0 for row in attribution)
    total_balance_change = sum(
        safe_float(item.get("balance_change")) or 0.0
        for item in balance_summary.values()
        if safe_float(item.get("balance_change")) is not None
    )
    lines.append(f"Closed-trade realised/attributed P&L: {_money_text(total_closed_pnl)}.")
    lines.append(f"Broker-fill reconstructed realised P&L: {_money_text(reconstructed.get('realized_pnl'))}.")
    if balance_summary:
        lines.append(f"Start-to-end portfolio balance movement across available broker snapshots: {_money_text(total_balance_change)}.")
    else:
        lines.append("Start-to-end portfolio balance movement is unavailable because no period snapshots were recorded.")
    lines.append(f"Closed trade count with full attribution: {len(attribution)}.")
    lines.append(f"Matched broker-fill round trips: {len(reconstructed.get('matched_trades') or [])}.")
    lines.append(f"Open/unmatched broker-fill lots: {len(reconstructed.get('open_lots') or [])}.")
    lines.append(f"Broker trade/order rows reviewed: {len(broker_trades)}.")
    if balance_summary and attribution:
        difference = total_balance_change - total_closed_pnl
        lines.append(f"Difference between balance movement and closed-trade attribution: {_money_text(difference)}. This can include open/unrealised P&L, deposits/withdrawals, fees, FX, or broker valuation movement.")
    return lines


def _report_likely_causes(
    snapshots: list[dict[str, Any]],
    attribution: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    broker_trades: list[dict[str, Any]],
    reconstructed: dict[str, Any],
) -> list[str]:
    causes: list[str] = []
    balance_summary = _balance_summary_by_broker(snapshots)
    for broker, item in balance_summary.items():
        change = safe_float(item.get("balance_change"))
        latest_day_pnl = safe_float(item["end"].get("day_pnl"))
        if change is not None and change < 0:
            causes.append(f"{broker.title()} start-to-end balance fell by {_money_text(change)} over the report window.")
        elif change is not None and change > 0:
            causes.append(f"{broker.title()} start-to-end balance rose by {_money_text(change)} over the report window.")
        if latest_day_pnl is not None and latest_day_pnl < 0:
            causes.append(f"{broker.title()} latest broker day P&L snapshot is negative at {_money_text(latest_day_pnl)}.")
        elif latest_day_pnl is not None and latest_day_pnl > 0:
            causes.append(f"{broker.title()} latest broker day P&L snapshot is positive at {_money_text(latest_day_pnl)}.")
    closed_losses = [row for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) < 0]
    closed_wins = [row for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) > 0]
    if closed_losses:
        symbols = Counter(str(row.get("symbol") or "unknown") for row in closed_losses)
        causes.append(f"Closed losing trades contributed {_money_text(sum(safe_float(row.get('profit_loss')) or 0.0 for row in closed_losses))}; symbols involved: {dict(symbols)}.")
    if closed_wins:
        symbols = Counter(str(row.get("symbol") or "unknown") for row in closed_wins)
        causes.append(f"Closed winning trades contributed {_money_text(sum(safe_float(row.get('profit_loss')) or 0.0 for row in closed_wins))}; symbols involved: {dict(symbols)}.")
    matched = reconstructed.get("matched_trades") or []
    open_lots = reconstructed.get("open_lots") or []
    if matched:
        wins = [row for row in matched if (safe_float(row.get("profit_loss")) or 0.0) > 0]
        losses = [row for row in matched if (safe_float(row.get("profit_loss")) or 0.0) < 0]
        if wins:
            causes.append(f"Matched broker fills show {len(wins)} profitable round trip(s), contributing {_money_text(sum(safe_float(row.get('profit_loss')) or 0.0 for row in wins))}.")
        if losses:
            causes.append(f"Matched broker fills show {len(losses)} losing round trip(s), contributing {_money_text(sum(safe_float(row.get('profit_loss')) or 0.0 for row in losses))}.")
    if open_lots:
        symbols = Counter(str(row.get("symbol") or "unknown") for row in open_lots)
        causes.append(f"{len(open_lots)} broker fill lot(s) remain open/unmatched in this window, so portfolio movement may be unrealised P&L; open symbols/lots: {dict(symbols)}.")
    if not attribution and broker_trades:
        causes.append("Broker trade/order rows exist, but no closed performance-attribution rows were recorded yet; part of the movement may be open/unrealised P&L.")
    if not attribution and not broker_trades:
        causes.append("No closed trade attribution or broker trade rows were recorded for this date; the loss is most likely from open-position mark-to-market movement captured in broker snapshots.")
    rejected = [row for row in decisions if row.get("decision") == "rejected"]
    if rejected:
        reasons = Counter(str(row.get("rejection_reason") or "unknown") for row in rejected)
        causes.append(f"Orchestrator rejected {len(rejected)} idea(s), mainly for: {dict(reasons)}.")
    return causes


def _latest_context_trade(report_context: dict[str, Any], broker: str) -> dict[str, Any] | None:
    contexts = report_context if broker == "all" else {broker: report_context.get(broker)}
    latest_items: list[dict[str, Any]] = []
    for payload in contexts.values():
        if not isinstance(payload, dict):
            continue
        latest = payload.get("latest_trade")
        if isinstance(latest, dict):
            latest_items.append(latest)
        for key in ["recent_activities", "recent_orders"]:
            for item in payload.get(key) or []:
                if isinstance(item, dict):
                    latest_items.append(item)
    latest_items.sort(
        key=lambda item: item.get("transaction_time") or item.get("submitted_at") or item.get("updated_at") or item.get("created_at") or "",
        reverse=True,
    )
    return latest_items[0] if latest_items else None


def _plain_english_report_answer(
    balance_summary: dict[str, dict[str, Any]],
    attribution: list[dict[str, Any]],
    broker_trades: list[dict[str, Any]],
    reconstructed: dict[str, Any],
    report_context: dict[str, Any],
    broker: str,
) -> list[str]:
    lines: list[str] = []
    if balance_summary:
        for name, item in balance_summary.items():
            change = safe_float(item.get("balance_change"))
            direction = "up" if (change or 0) > 0 else "down" if (change or 0) < 0 else "flat"
            lines.append(
                f"{name.title()} is {direction} by {_money_text(change)} over this report window. "
                f"Latest account value is {_money_text(item.get('end_balance'))}, cash is {_money_text(item.get('end_cash'))}, "
                f"and about {_money_text(item.get('end_in_positions'))} appears to be tied up in open positions."
            )
    else:
        lines.append("No portfolio snapshots were found for this report window, so the app cannot prove start-to-end performance from stored balances.")

    realised = sum(safe_float(row.get("profit_loss")) or 0.0 for row in attribution)
    reconstructed_realised = safe_float(reconstructed.get("realized_pnl")) or 0.0
    if attribution:
        lines.append(f"Closed trade attribution says realised P&L was {_money_text(realised)} across {len(attribution)} closed trade(s).")
    elif reconstructed.get("matched_trades"):
        lines.append(f"Broker fills could be matched into realised P&L of {_money_text(reconstructed_realised)} across {len(reconstructed.get('matched_trades') or [])} round trip(s).")
    elif broker_trades:
        lines.append("Broker rows were found, but no complete buy/sell round trip was found in this window, so any gain or loss is probably still open/unrealised or from activity outside this window.")
    else:
        lines.append("No broker fills/orders were found in this report window. If the account moved, it was probably existing open-position value changing rather than a new closed trade today.")

    latest = _latest_context_trade(report_context, broker)
    if latest:
        lines.append(
            f"Latest visible broker activity: {str(latest.get('side') or latest.get('type') or '').upper()} "
            f"{latest.get('symbol') or latest.get('pair') or 'unknown'} for {latest.get('qty') or latest.get('quantity') or 'unknown'} "
            f"at {_money_text(latest.get('price') or latest.get('filled_avg_price'))}."
        )
    lines.append("Learning note: AI Trader should only claim trading-skill improvement from completed trades with entry, exit, and P&L. Open positions are useful evidence, but they are not final lessons yet.")
    return lines


def _current_open_position_lines(report_context: dict[str, Any], broker: str) -> str:
    contexts = report_context if broker == "all" else {broker: report_context.get(broker)}
    lines: list[str] = []
    for broker_name, payload in contexts.items():
        if not isinstance(payload, dict):
            continue
        positions = payload.get("open_positions") or []
        portfolio_value = payload.get("portfolio_value")
        cash = payload.get("cash_available")
        invested = _estimated_in_positions(portfolio_value, cash)
        if invested is not None:
            lines.append(f"- {_broker_label(broker_name)}: estimated {_money_text(invested)} currently tied up outside cash.")
        if positions:
            for position in positions[:20]:
                if not isinstance(position, dict):
                    continue
                symbol = position.get("symbol") or position.get("asset") or position.get("pair") or "unknown"
                qty = position.get("qty") or position.get("quantity") or position.get("vol") or "N/A"
                market_value = position.get("market_value") or position.get("value") or position.get("notional")
                unrealized = position.get("unrealized_pl") or position.get("unrealised_pnl")
                lines.append(f"  - {symbol}: qty {qty}, value {_money_text(market_value)}, unrealised P&L {_money_text(unrealized)}.")
        elif invested is not None and abs(invested) > 0.01:
            lines.append(f"  - Broker did not return position detail, but portfolio minus cash implies open holdings worth about {_money_text(invested)}.")
    return "\n".join(lines) if lines else "- No open position detail was available from broker refresh."


def _report_trade_lines(attribution: list[dict[str, Any]]) -> str:
    if not attribution:
        return "- No closed trade attribution rows recorded for this report window."
    lines = []
    for index, row in enumerate(attribution, start=1):
        lines.append(
            f"- Trade {index}: {row.get('broker', 'unknown')} {row.get('symbol', 'unknown')} {row.get('side', '')}; "
            f"opened {_human_time(row.get('opened_at'))}; closed {_human_time(row.get('closed_at') or row.get('created_at'))}; "
            f"entry {_money_text(row.get('entry_price'))}, exit {_money_text(row.get('exit_price'))}, "
            f"qty {row.get('quantity') or 'N/A'}, P&L {_money_text(row.get('profit_loss'))}, "
            f"entry reason {row.get('entry_reason') or 'N/A'}, exit reason {row.get('exit_reason') or 'N/A'}."
        )
    return "\n".join(lines)


def _report_broker_trade_lines(broker_trades: list[dict[str, Any]]) -> str:
    if not broker_trades:
        return "- No broker trade/order rows recorded for this report window."
    lines = []
    for index, row in enumerate(broker_trades, start=1):
        parsed = _broker_trade_payload(row)
        event_time = _broker_trade_time(row)
        side = _broker_trade_side(row)
        symbol = _broker_trade_symbol(row)
        quantity = _broker_trade_quantity(row)
        price = _broker_trade_price(row)
        lines.append(
            f"- Row {index}: {row.get('broker', 'unknown')} {symbol or 'N/A'} {side or ''}; "
            f"status {row.get('status') or 'N/A'}; opened {_human_time(row.get('opened_at'))}; "
            f"closed {_human_time(row.get('closed_at'))}; updated {_human_time(row.get('updated_at'))}; event time {_human_time(event_time)}; "
            f"qty {quantity if quantity is not None else 'N/A'}; price {_money_text(price)}; notional {_money_text(row.get('notional') or parsed.get('net_amount'))}; "
            f"raw type {parsed.get('type') or parsed.get('activity_type') or 'N/A'}."
        )
    return "\n".join(lines)


def _reconstruct_broker_fill_pnl(broker_trades: list[dict[str, Any]]) -> dict[str, Any]:
    lots: dict[str, list[dict[str, Any]]] = defaultdict(list)
    matched: list[dict[str, Any]] = []
    fill_rows = [
        row for row in broker_trades
        if _broker_trade_side(row) in {"buy", "sell"}
        and _broker_trade_quantity(row) is not None
        and _broker_trade_price(row) is not None
    ]
    fill_rows.sort(key=lambda row: _broker_trade_time(row) or row.get("updated_at") or "")
    for row in fill_rows:
        symbol = _broker_trade_symbol(row) or "UNKNOWN"
        side = _broker_trade_side(row) or ""
        qty_remaining = _broker_trade_quantity(row) or 0.0
        price = _broker_trade_price(row) or 0.0
        event_time = _broker_trade_time(row)
        opposite = "sell" if side == "buy" else "buy"
        same_lots = lots[symbol]
        while qty_remaining > 0 and same_lots and same_lots[0]["side"] == opposite:
            lot = same_lots[0]
            close_qty = min(qty_remaining, lot["quantity"])
            if lot["side"] == "buy" and side == "sell":
                pnl = (price - lot["price"]) * close_qty
                entry_side = "buy"
            else:
                pnl = (lot["price"] - price) * close_qty
                entry_side = "sell"
            matched.append({
                "broker": row.get("broker"),
                "symbol": symbol,
                "entry_side": entry_side,
                "exit_side": side,
                "quantity": close_qty,
                "entry_price": lot["price"],
                "exit_price": price,
                "entry_time": lot.get("time"),
                "exit_time": event_time,
                "profit_loss": pnl,
                "reason": "FIFO match from broker fill history in this report window.",
            })
            lot["quantity"] -= close_qty
            qty_remaining -= close_qty
            if lot["quantity"] <= 1e-9:
                same_lots.pop(0)
        if qty_remaining > 1e-9:
            same_lots.append({
                "broker": row.get("broker"),
                "symbol": symbol,
                "side": side,
                "quantity": qty_remaining,
                "price": price,
                "time": event_time,
                "reason": "No matching opposite-side fill inside this report window.",
            })
    open_lots = [lot for symbol_lots in lots.values() for lot in symbol_lots]
    realized_pnl = sum(safe_float(row.get("profit_loss")) or 0.0 for row in matched)
    return {"matched_trades": matched, "open_lots": open_lots, "realized_pnl": realized_pnl}


def _reconstructed_trade_lines(reconstructed: dict[str, Any]) -> str:
    matched = reconstructed.get("matched_trades") or []
    open_lots = reconstructed.get("open_lots") or []
    lines: list[str] = []
    if matched:
        for index, row in enumerate(matched, start=1):
            result = "made" if (safe_float(row.get("profit_loss")) or 0.0) >= 0 else "lost"
            lines.append(
                f"- Matched trade {index}: {row.get('broker', 'unknown')} {row.get('symbol')} "
                f"{row.get('entry_side')}->{row.get('exit_side')}; opened {_human_time(row.get('entry_time'))}; "
                f"closed {_human_time(row.get('exit_time'))}; qty {row.get('quantity')}; "
                f"entry {_money_text(row.get('entry_price'))}; exit {_money_text(row.get('exit_price'))}; "
                f"{result} {_money_text(abs(safe_float(row.get('profit_loss')) or 0.0))}; P&L {_money_text(row.get('profit_loss'))}; "
                f"reason: {row.get('reason')}."
            )
    else:
        lines.append("- No buy/sell fills could be matched into a closed round trip inside this report window.")
    if open_lots:
        lines.append("- Open/unmatched fills:")
        for row in open_lots:
            lines.append(
                f"  - {row.get('broker', 'unknown')} {row.get('symbol')} {row.get('side')}; "
                f"time {_human_time(row.get('time'))}; qty {row.get('quantity')}; price {_money_text(row.get('price'))}; "
                f"reason: {row.get('reason')}"
            )
    return "\n".join(lines)


def _report_decision_lines(decisions: list[dict[str, Any]]) -> str:
    rejected = [row for row in decisions if row.get("decision") == "rejected"]
    if not rejected:
        return "- No rejected orchestrator decisions recorded for this date."
    return "\n".join(
        f"- {row.get('symbol', 'unknown')} via {row.get('selected_broker') or 'unknown'}: {row.get('rejection_reason') or 'rejected'}"
        for row in rejected[:20]
    )


def _dedupe_lines(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _period_lessons(
    attribution: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
    broker_trades: list[dict[str, Any]],
    base_lessons: list[str],
) -> list[str]:
    lessons = list(base_lessons)
    losses = [row for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) < 0]
    wins = [row for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) > 0]
    if losses:
        exit_reasons = Counter(str(row.get("exit_reason") or "unknown") for row in losses)
        lessons.append(f"Loss-making closed trades should be reviewed by exit reason before the next trading cycle: {dict(exit_reasons)}.")
        lessons.append("For the next trades, require the entry thesis to explain why the setup is stronger than the losing trades in this report window.")
    if wins:
        entry_reasons = Counter(str(row.get("entry_reason") or "unknown") for row in wins)
        lessons.append(f"Winning closed trades shared these entry reasons: {dict(entry_reasons)}. Future trades should explicitly compare against these patterns.")
    if not attribution and broker_trades:
        lessons.append("Broker activity exists without closed attribution; improve reconciliation before drawing firm conclusions about realised strategy quality.")
    if snapshots and not attribution:
        lessons.append("Balance movement without closed attribution suggests open-position/unrealised P&L or valuation movement; avoid changing strategy until open trades are reconciled.")
    rejected = [row for row in decisions if row.get("decision") == "rejected"]
    if rejected:
        reasons = Counter(str(row.get("rejection_reason") or "unknown") for row in rejected)
        lessons.append(f"Rejected recommendations show what the system avoided: {dict(reasons)}.")
    return _dedupe_lines(lessons)


def _period_recommendations(attribution: list[dict[str, Any]], decisions: list[dict[str, Any]], base_recommendations: list[str]) -> list[str]:
    recommendations = list(base_recommendations)
    losses = [row for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) < 0]
    if losses:
        recommendations.append("Before approving larger size, review each losing trade's entry timing, stop distance, and whether the exit matched the planned stop/take-profit.")
        recommendations.append("Keep or reduce position size until the next report shows that losses are smaller than winners over the same period.")
    if not attribution:
        recommendations.append("Do not infer profitability from broker balance movement alone; wait for closed-trade attribution or inspect open positions.")
    rejected = [row for row in decisions if row.get("decision") == "rejected"]
    if rejected:
        recommendations.append("Do not loosen guardrails purely to increase trade count; repeated rejection reasons should be reviewed by the Founder first.")
    return _dedupe_lines(recommendations)


class ReportingService:
    """The report pipeline (architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md
    Phase 3): trading_report/report_page/report generation, moved out of LocalApiService.

    `portfolio_lookup` and `daily_learning_lookup` are narrow, explicit injected
    dependencies for the two things this pipeline needs from LocalApiService methods that
    have not been extracted yet (`portfolio()` is Phase 6 broker/operations territory;
    `daily_learning_update()` is research/learning territory, not reporting) -- per the
    plan's Section 5 dependency rule 6: "Cross-service dependencies should go through
    explicit domain services or the application context," not a reference to the whole
    LocalApiService object.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        audit: AuditDatabase,
        query_executor: QueryExecutor,
        portfolio_lookup: Callable[[str], dict[str, Any]],
        daily_learning_lookup: Callable[[str | None], dict[str, Any]],
    ) -> None:
        self.settings = settings
        self.audit = audit
        self._query_executor = query_executor
        self._portfolio_lookup = portfolio_lookup
        self._daily_learning_lookup = daily_learning_lookup

    def initialize_schema(self) -> None:
        # Process-level schema-once guard (Phase 9, architecture/AI_TRADER_MODULARISATION_
        # ARCHITECTURE_2026-08-02.md): this used to just run REPORT_SCHEMA's executescript
        # directly, relying on its one call site in LocalApiService.__init__ to make it
        # naturally run only once per process. record_trading_report (below) independently
        # re-ran the same executescript on every single persisted report -- a genuine
        # redundant-schema-work bug, documented but deliberately left unfixed by Phase 3 to
        # keep that extraction a pure move. Both call sites now go through the same
        # ensure_schema_once guard already used by every other schema-owning module in this
        # codebase, so record_trading_report's defensive call (needed for the "worker owns
        # runtime" split-process path, where this LocalApiService instance's own __init__
        # never calls this method) is now free after the first call in either order.
        def _init() -> None:
            with closing(self._query_executor.connect()) as conn:
                with conn:
                    conn.executescript(REPORT_SCHEMA)

        ensure_schema_once(self.settings.db_path, "reporting_service", _init)

    def generate_report(self, body: dict[str, Any]) -> dict[str, Any]:
        report_type = str(body.get("type") or "daily").lower()
        broker = str(body.get("broker") or "all").lower()
        report_date = str(body.get("date") or date.today().isoformat())
        return self.trading_report(report_date=report_date, broker=broker, report_type=report_type, persist=True)

    def trading_report(self, *, report_date: str | None, broker: str = "all", report_type: str = "daily", persist: bool = False) -> dict[str, Any]:
        report_date = report_date or date.today().isoformat()
        broker = (broker or "all").lower()
        report_type = (report_type or "daily").lower()
        try:
            parsed_date = date.fromisoformat(report_date)
        except ValueError:
            parsed_date = date.today()
            report_date = parsed_date.isoformat()
        report_context = self.refresh_report_sources(broker)
        if report_type in {"morning", "evening"}:
            markdown = self.broker_learning_report_markdown(parsed_date, broker, report_type, report_context)
        else:
            markdown = self.broker_learning_report_markdown(parsed_date, broker, report_type, report_context)
            if persist and broker == "all":
                self.audit.record_briefing(report_date, markdown, {"report_type": report_type, "broker": broker})
        path = self.write_trading_report(report_date, broker, report_type, markdown) if persist else None
        summary = _first_markdown_bullet(markdown) or f"{report_type.title()} report generated for {broker.title()} on {report_date}."
        report_id = self.record_trading_report(
            report_date=report_date,
            broker=broker,
            report_type=report_type,
            summary=summary,
            markdown=markdown,
            path=path,
        ) if persist else None
        if persist:
            record_notification(
                self.settings.db_path,
                event_type="trading_report_generated",
                broker=None if broker == "all" else broker,
                symbol=None,
                title=f"{report_type.title()} report generated",
                message=summary,
                payload={"date": report_date, "broker": broker, "report_type": report_type, "path": str(path) if path else None, "report_id": report_id},
            )
        return {
            "status": "generated" if persist else "available",
            "report_id": report_id,
            "date": report_date,
            "broker": broker,
            "report_type": report_type,
            "summary": summary,
            "report_markdown": markdown,
            "path": str(path) if path else None,
            "report_url": f"/reports/{report_id}" if report_id is not None else None,
            "generated_at": utc_now_iso(),
        }

    def report_page(self, path: str) -> tuple[int, dict[str, Any]]:
        report_id_text = path.removeprefix("/reports/").split("/", 1)[0].removesuffix(".html")
        try:
            report_id = int(report_id_text)
        except ValueError:
            return 404, {"error": "not_found", "path": path}
        row = self._query_executor.row("SELECT * FROM TRADING_REPORTS WHERE report_id = ?", (report_id,))
        if not row:
            return 404, {"error": "not_found", "path": path}
        title = f"AI Trader {row['report_type'].title()} Report - {row['broker']} - {row['report_date']}"
        escaped_title = html.escape(title)
        escaped_summary = html.escape(row["summary"] or "")
        escaped_markdown = html.escape(row["report_markdown"] or "")
        escaped_path = html.escape(row["file_path"] or "Saved to the database record only; no separate file was written.")
        page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; background: #f6f7f9; color: #17202a; }}
    main {{ max-width: 960px; margin: 0 auto; background: #fff; border: 1px solid #dde1e7; border-radius: 8px; padding: 20px; }}
    h1 {{ font-size: 24px; margin-top: 0; }}
    .meta {{ color: #667085; font-size: 14px; margin-bottom: 18px; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; font-family: inherit; line-height: 1.45; }}
  </style>
</head>
<body>
  <main>
    <h1>{escaped_title}</h1>
    <div class="meta">Generated: {html.escape(_human_time(row['created_at']))}<br>Saved file: {escaped_path}</div>
    <p><strong>Summary:</strong> {escaped_summary}</p>
    <pre>{escaped_markdown}</pre>
  </main>
</body>
</html>"""
        return 200, {"html": page}

    def refresh_report_sources(self, broker: str) -> dict[str, Any]:
        brokers = ["alpaca", "kraken", "coinbase"] if broker == "all" else [broker]
        refreshed: dict[str, Any] = {}
        for name in brokers:
            try:
                refreshed[name] = self._portfolio_lookup(name)
            except Exception as exc:
                logger.exception("Failed to refresh %s before report generation.", name)
                refreshed[name] = {"broker": name, "error": str(exc)}
        return refreshed

    def broker_learning_report_markdown(self, report_date: date, broker: str, report_type: str, report_context: dict[str, Any] | None = None) -> str:
        period = _report_period(report_date, report_type)
        start = period["start"]
        end = period["end"]
        broker_filter = "" if broker == "all" else " AND LOWER(broker) = LOWER(?)"
        broker_params: tuple[Any, ...] = () if broker == "all" else (broker,)
        snapshots = [
            dict(row)
            for row in self._query_executor.rows(
                f"""
                SELECT broker, exchange, created_at, portfolio_value, cash, buying_power, day_pnl, week_pnl, month_pnl, open_positions_count
                FROM PORTFOLIO_SNAPSHOTS
                WHERE created_at >= ? AND created_at <= ?{broker_filter}
                ORDER BY created_at ASC
                """,
                (start, end, *broker_params),
            )
        ]
        attribution = [
            dict(row)
            for row in self._query_executor.rows(
                f"""
                SELECT * FROM PERFORMANCE_ATTRIBUTION
                WHERE COALESCE(closed_at, created_at) >= ? AND COALESCE(closed_at, created_at) <= ?{broker_filter}
                ORDER BY COALESCE(closed_at, created_at) ASC, attribution_id ASC
                """,
                (start, end, *broker_params),
            )
        ]
        decisions = [
            dict(row)
            for row in self._query_executor.rows(
                f"""
                SELECT * FROM ORCHESTRATOR_DECISIONS
                WHERE created_at >= ? AND created_at <= ?
                {'' if broker == 'all' else 'AND LOWER(selected_broker) = LOWER(?)'}
                ORDER BY decision_id DESC
                LIMIT 30
                """,
                (start, end, *broker_params),
            )
        ]
        broker_trades = [
            dict(row)
            for row in self._query_executor.rows(
                f"""
                SELECT * FROM BROKER_TRADE_HISTORY
                WHERE COALESCE(closed_at, opened_at, updated_at) >= ? AND COALESCE(closed_at, opened_at, updated_at) <= ?{broker_filter}
                ORDER BY COALESCE(closed_at, opened_at, updated_at) ASC, trade_history_id ASC
                """,
                (start, end, *broker_params),
            )
        ]
        learning = self._daily_learning_lookup(report_date.isoformat())
        if broker != "all":
            learning = {
                **learning,
                "closed_trades": [row for row in learning.get("closed_trades", []) if str(row.get("broker") or "").lower() == broker],
            }
        total_closed_pnl = sum(safe_float(row.get("profit_loss")) or 0.0 for row in attribution)
        losing_trades = [row for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) < 0]
        winning_trades = [row for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) > 0]
        reconstructed = _reconstruct_broker_fill_pnl(broker_trades)
        balance_summary = _balance_summary_by_broker(snapshots)
        performance_lines = _performance_summary_lines(balance_summary, attribution, broker_trades, reconstructed)
        likely_causes = _report_likely_causes(snapshots, attribution, decisions, broker_trades, reconstructed)
        report_context = report_context or {}
        open_position_lines = _current_open_position_lines(report_context, broker)
        plain_english = _plain_english_report_answer(balance_summary, attribution, broker_trades, reconstructed, report_context, broker)
        markdown = f"""# AI Trader {report_type.title()} Trading Report

Report Date: {report_date.isoformat()}
Period: {period["label"]}
Window Start: {_human_time(start)}
Window End: {_human_time(end)}
Broker: {broker.title() if broker != "all" else "All brokers"}

## Plain English Executive Answer

{_list_or_none(plain_english)}

## Evidence Summary

- Start/end balance snapshots reviewed: {len(balance_summary)} broker(s).
- Closed trade P&L recorded in attribution: {_money_text(total_closed_pnl)}.
- Broker-fill reconstructed realised P&L: {_money_text(reconstructed["realized_pnl"])}.
- Closed winners: {len(winning_trades)}.
- Closed losers: {len(losing_trades)}.
- Matched broker-fill round trips: {len(reconstructed["matched_trades"])}.
- Open/unmatched broker-fill lots: {len(reconstructed["open_lots"])}.
- Orchestrator decisions reviewed: {len(decisions)}.
- Broker trade-history rows reviewed: {len(broker_trades)}.

## Start And End Balances

{_balance_summary_lines(balance_summary)}

## What You Currently Own Or Have Open

{open_position_lines}

## Performance Over The Period

{_list_or_none(performance_lines)}

## Why Performance Moved

{_list_or_none(likely_causes)}

## Reconstructed Broker Fill P&L

{_reconstructed_trade_lines(reconstructed)}

## All Closed Trades With Entry, Exit, Times, And P&L

{_report_trade_lines(attribution)}

## Broker Fills And Orders Seen

{_report_broker_trade_lines(broker_trades)}

## Guardrail And Orchestrator Rejections

{_report_decision_lines(decisions)}

## Lessons Learned

{_list_or_none(_period_lessons(attribution, decisions, snapshots, broker_trades, learning.get("trade_lessons") or []))}

## Successful Trader / Benchmark Learning

{_list_or_none(learning.get("benchmark_learning") or [])}

## Recommendations For Founder Approval

{_list_or_none(_period_recommendations(attribution, decisions, learning.get("recommendations_for_founder") or []))}

## Important Note

This report explains available evidence. It does not automatically change strategy, guardrails, broker permissions, or execution logic.
"""
        return markdown

    def write_trading_report(self, report_date: str, broker: str, report_type: str, markdown: str) -> Path:
        report_dir = self.settings.output_dir / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        safe_broker = "".join(ch for ch in broker.lower() if ch.isalnum() or ch in {"-", "_"}) or "all"
        safe_type = "".join(ch for ch in report_type.lower() if ch.isalnum() or ch in {"-", "_"}) or "daily"
        path = report_dir / f"{safe_type}_trading_report_{safe_broker}_{report_date}.md"
        path.write_text(markdown, encoding="utf-8")
        return path

    def record_trading_report(
        self,
        *,
        report_date: str,
        broker: str,
        report_type: str,
        summary: str,
        markdown: str,
        path: Path | None,
    ) -> int:
        # Fixed in Phase 9 (was: re-ran REPORT_SCHEMA's executescript on every single
        # persisted report -- flagged as a known bug, deliberately left unfixed, in Phase
        # 3's log entry). Now goes through the same ensure_schema_once guard as
        # initialize_schema() itself, so this is a no-op after the first call in either
        # order, per process -- see initialize_schema()'s docstring comment above.
        self.initialize_schema()
        with closing(connect(self.settings.db_path)) as conn:
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO TRADING_REPORTS (
                        created_at, report_date, broker, report_type, summary,
                        report_markdown, file_path
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (utc_now_iso(), report_date, broker, report_type, summary, markdown, str(path) if path else None),
                )
                return int(cursor.lastrowid)
