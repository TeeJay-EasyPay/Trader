"""Settle the trades the app decided against, so declining one still teaches it something.

Founder-directed 2026-09-05, Phase 3 of the learning work.

WHY THIS EXISTS. SHADOW_TRADES records every candidate this app would have taken -- symbol,
strategy, regime, entry, stop, target -- whether or not it was actually traded. On
2026-09-05 it held 2,312 rows and **every single one** was `outcome_status='pending'` with no
result. The app has been diligently writing down its own hypothetical trades for weeks and
has never once looked up how they turned out.

That matters for two separate reasons.

  1. It is the only learning input that does not need real money. 26 closed trades is far too
     few to judge sixteen strategies; 2,312 shadow candidates is not.
  2. It is the route back for a demoted strategy. `strategy_demotion` removes a strategy's
     real-money permission, and crypto only ever trades live -- so without shadow evidence a
     demoted crypto strategy can never accumulate the record needed to earn it back. That is
     the August doom loop in a new place, and this is what closes it.

HOW A SHADOW TRADE IS SETTLED. Walk the daily candles that came AFTER the candidate was
recorded and ask which happened first: the stop or the target.

  * stop first  -> -1R (the whole point of a stop is that it caps the loss at one unit)
  * target first -> the planned reward:risk, in R
  * neither, and the window has run out -> settled at the last close, in R
  * no candles after it yet -> left pending, because guessing is worse than waiting

WHEN A SINGLE CANDLE SPANS BOTH stop and target, the stop is recorded. Daily bars cannot say
which came first intraday, and assuming the good outcome would systematically flatter every
result. That is the same deliberate pessimism `backtest.py` already applies, documented there;
it understates rather than overstates, which is the right direction for a number that will
later be used to hand a strategy real money back.

FEES ARE CHARGED. `estimated_net_r` subtracts the measured round-trip cost expressed in R,
because a shadow trade that ignores fees is not comparable with a real one -- and this app's
fees are large enough (about 1.58% of notional) to turn a genuinely positive gross edge
negative. Gross is stored alongside so the two can be told apart.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .database import connect
from .learning_readiness import _parse as _parse_stamp
from .shadow_settlement import SETTLEMENT_SCHEMA_VERSION, adapter_for

# A candidate is abandoned rather than settled once this long has passed without either level
# being reached. Matches the 24h freshness a real recommendation gets, times a working week:
# beyond that the trade the app was considering is not the trade the market is now offering.
SHADOW_HORIZON_DAYS = 7
# Extra days beyond the horizon before a still-unsettleable trade is retired -- see
# _note_unsettleable for why retiring on the first failure would lose real results.
SHADOW_SETTLE_GRACE_DAYS = 3

# Measured round-trip cost on this account, from settled trades. The same figure the live fee
# hurdle uses, kept here as a fallback for when no measurement is available.
DEFAULT_ROUND_TRIP_FEE_PCT = 0.0158


@dataclass(frozen=True)
class ShadowOutcome:
    shadow_trade_id: Any
    symbol: str
    strategy: str | None
    outcome_status: str          # "target_hit" | "stop_hit" | "expired" | "pending"
    gross_r: float | None
    estimated_net_r: float | None
    final_price: float | None
    holding_time_minutes: float | None


def _load_candles(conn: Any, symbols: set[tuple[str, str]], *,
                  start_at: datetime | None = None,
                  end_at: datetime | None = None) -> dict[tuple[str, str], list[tuple[datetime, float, float, float]]]:
    """Daily OHLC for every symbol needed, in ONE query, oldest first.

    Loaded up front rather than per shadow trade. The first version queried inside the loop
    and took 115 seconds to settle 385 candidates against a database on another continent --
    the same N+1 shape that makes broker-poll-kraken time out. One query, then pure arithmetic.
    """
    if not symbols:
        return {}
    market_symbols = sorted({symbol for _asset, symbol in symbols})
    placeholders = ",".join("?" for _ in market_symbols)
    rows = conn.execute(
        f"""
        SELECT UPPER(normalized_symbol), LOWER(asset_type), observation_time, high, low, close
        FROM MARKET_DATA_OBSERVATIONS
        WHERE timeframe = '1d' AND UPPER(normalized_symbol) IN ({placeholders})
          AND (? IS NULL OR observation_time > ?)
          AND (? IS NULL OR observation_time <= ?)
        ORDER BY observation_time
        """,
        (*market_symbols,
         start_at.isoformat() if start_at else None, start_at.isoformat() if start_at else None,
         end_at.isoformat() if end_at else None, end_at.isoformat() if end_at else None),
    ).fetchall()
    out: dict[tuple[str, str], list[tuple[datetime, float, float, float]]] = {}
    for row in rows:
        # Five-column form is retained for small legacy test/local adapters that predate
        # asset_type. Production returns six and is always broker separated.
        legacy = len(row) == 5
        asset, symbol = ("crypto", str(row[0]).upper()) if legacy else (str(row[1]).lower(), str(row[0]).upper())
        stamp = _parse_stamp(row[1] if legacy else row[2])
        if stamp is None:
            continue
        try:
            offset = 1 if legacy else 2
            out.setdefault((asset, symbol), []).append(
                (stamp, float(row[offset+1]), float(row[offset+2]), float(row[offset+3]))
            )
            if legacy and asset == "crypto" and not symbol.endswith("GBP"):
                out.setdefault((asset, symbol + "GBP"), []).append(
                    (stamp, float(row[offset+1]), float(row[offset+2]), float(row[offset+3]))
                )
        except (TypeError, ValueError):
            continue
    return out


def _window(candles: list[tuple[datetime, float, float, float]],
            start: datetime, horizon: datetime) -> list[tuple[datetime, float, float, float]]:
    return [c for c in candles if start < c[0] <= horizon]


def resolve_shadow_trades(
    db_path: Path,
    *,
    limit: int = 500,
    round_trip_fee_pct: float = DEFAULT_ROUND_TRIP_FEE_PCT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Settle pending shadow candidates against real price history.

    Bounded by `limit` so one run cannot consume a worker's whole budget; anything left stays
    pending and is picked up next time. Never raises.
    """
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    legacy_reconciliation = reconcile_legacy_shadow_rows(db_path, limit=min(int(limit), 500), now=moment)
    settled: list[ShadowOutcome] = []
    still_pending = 0
    unsettleable: list[Any] = []
    try:
        with closing(connect(db_path)) as conn:
            rows = conn.execute(
                """
                SELECT shadow_trade_id, created_at, symbol, strategy, intended_entry,
                       stop_loss, take_profit, intended_broker, asset_type, quantity,
                       simulated_costs_json
                FROM SHADOW_TRADES
                WHERE outcome_status = 'pending'
                ORDER BY created_at
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()

            normalized = {}
            for raw in rows:
                data = dict(raw) if hasattr(raw, "keys") else dict(zip(
                    ("shadow_trade_id","created_at","symbol","strategy","intended_entry",
                     "stop_loss","take_profit","intended_broker","asset_type","quantity",
                     "simulated_costs_json"), raw))
                data.setdefault("intended_broker", "kraken")
                data.setdefault("asset_type", "crypto")
                data.setdefault("quantity", 1.0)
                data.setdefault("simulated_costs_json", "{}")
                try:
                    normalized[data["shadow_trade_id"]] = adapter_for(data["intended_broker"]).normalize(data)
                except ValueError:
                    normalized[data["shadow_trade_id"]] = None
            created_values = [_parse_stamp(row[1]) for row in rows]
            created_values = [value for value in created_values if value is not None]
            candles_by_symbol = _load_candles(conn, {
                (trade.asset_class, trade.market_symbol) for trade in normalized.values() if trade
            }, start_at=min(created_values) if created_values else None,
                end_at=min(moment, max(created_values) + timedelta(days=SHADOW_HORIZON_DAYS)) if created_values else moment)

            for row in rows:
                created = _parse_stamp(row[1])
                trade = normalized.get(row[0])
                if created is None or trade is None:
                    still_pending += 1
                    _note_unsettleable(unsettleable, row[0], created, moment)
                    continue
                entry, stop, target = trade.entry, trade.stop, trade.target
                risk_per_unit = entry - stop
                if risk_per_unit <= 0:
                    still_pending += 1
                    _note_unsettleable(unsettleable, row[0], created, moment)
                    continue

                horizon = created + timedelta(days=SHADOW_HORIZON_DAYS)
                candles = _window(
                    candles_by_symbol.get((trade.asset_class, trade.market_symbol), []), created, horizon
                )
                if not candles:
                    still_pending += 1
                    _note_unsettleable(unsettleable, row[0], created, moment)
                    continue

                planned_r = (target - entry) / risk_per_unit
                status, gross_r, final_price, closed_at = "expired", None, None, None
                for stamp, high, low, close in candles:
                    # Stop first when a single day spans both: a daily bar cannot say which
                    # came first intraday, and assuming the target would flatter every result.
                    if low <= stop:
                        status, gross_r, final_price, closed_at = "stop_hit", -1.0, stop, stamp
                        break
                    if high >= target:
                        status, gross_r, final_price, closed_at = "target_hit", planned_r, target, stamp
                        break
                if gross_r is None:
                    # A partial history is not expiry. Keep the candidate open until its
                    # full observation horizon has passed, so later levels can still settle it.
                    if moment < horizon:
                        still_pending += 1
                        continue
                    stamp, _high, _low, close = candles[-1]
                    status, final_price, closed_at = "expired", close, stamp
                    gross_r = (close - entry) / risk_per_unit

                # Fees in R: the round trip costs a share of notional, and notional is entry
                # size, so the cost in units of risk is fee_pct * entry / risk_per_unit.
                adapter = adapter_for(trade.broker)
                fee_r = adapter.cost_r(trade, risk_per_unit)
                if fee_r is None:
                    still_pending += 1
                    _note_unsettleable(unsettleable, row[0], created, moment)
                    continue
                net_r = gross_r - fee_r
                holding_minutes = (
                    (closed_at - created).total_seconds() / 60.0 if closed_at else None
                )
                settled.append(ShadowOutcome(
                    shadow_trade_id=row[0], symbol=trade.symbol, strategy=row[3],
                    outcome_status=status, gross_r=round(gross_r, 4),
                    estimated_net_r=round(net_r, 4), final_price=final_price,
                    holding_time_minutes=round(holding_minutes, 2) if holding_minutes else None,
                ))

            # 2026-09-06: retire rows that can never be settled, so they stop blocking the
            # queue. This query is ORDER BY created_at LIMIT 500, so the OLDEST pending rows
            # are read first -- and a row with no candles, no prices or a non-positive risk is
            # skipped and left pending, forever. Measured on production: 543 rows pending and
            # more than ten days old against a seven-day horizon, permanently occupying the 500
            # slots, so NEWER shadow trades were never settled at all and the scoreboard
            # silently stopped updating.
            #
            # It was also pure waste: the same ~500 unsettleable rows re-read 287 times a day.
            #
            # 'unsettleable' rather than 'expired' deliberately. An expired shadow trade ran its
            # full horizon and produced a real result; these produced none, and calling them
            # expired would quietly fold "we could not measure this" into the strategy record as
            # if it were a measured outcome. estimated_net_r stays NULL, so the scoreboard
            # continues to ignore them.
            if unsettleable:
                with conn:
                    conn.executemany(
                        """
                        UPDATE SHADOW_TRADES SET outcome_status = 'unsettleable', updated_at = ?
                        WHERE shadow_trade_id = ? AND outcome_status = 'pending'
                        """,
                        [(moment.isoformat(), sid) for sid in unsettleable],
                    )
            for outcome in settled:
                settled_trade = normalized.get(outcome.shadow_trade_id)
                provenance = (
                    f"schema:v{SETTLEMENT_SCHEMA_VERSION}:{settled_trade.broker}:"
                    f"{settled_trade.asset_class}:{settled_trade.currency}:{settled_trade.cost_basis}"
                    if settled_trade else f"schema:v{SETTLEMENT_SCHEMA_VERSION}:unknown"
                )
                with conn:
                    conn.execute(
                        """
                        UPDATE SHADOW_TRADES
                        SET outcome_status = ?, gross_r = ?, estimated_net_r = ?,
                            final_price = ?, holding_time_minutes = ?, updated_at = ?,
                            benchmark_outcome = ?
                        WHERE shadow_trade_id = ?
                        """,
                        (outcome.outcome_status, outcome.gross_r, outcome.estimated_net_r,
                         outcome.final_price, outcome.holding_time_minutes,
                         moment.isoformat(),
                         provenance,
                         outcome.shadow_trade_id),
                    )
    except Exception as exc:  # noqa: BLE001 - a settlement failure must never stop the worker
        return {"status": "failed", "reason": f"{type(exc).__name__}: {exc}",
                "settled": 0, "still_pending": still_pending}

    by_status: dict[str, int] = {}
    for outcome in settled:
        by_status[outcome.outcome_status] = by_status.get(outcome.outcome_status, 0) + 1
    return {
        "status": "settled" if settled else "nothing_to_settle",
        "settled": len(settled),
        "still_pending": still_pending,
        "retired_unsettleable": len(unsettleable),
        "by_outcome": by_status,
        "schema_version": SETTLEMENT_SCHEMA_VERSION,
        "adapters": sorted({trade.broker for trade in normalized.values() if trade}),
        "legacy_reconciliation": legacy_reconciliation,
    }


def reconcile_legacy_shadow_rows(db_path: Path, *, limit: int = 500,
                                 now: datetime | None = None) -> dict[str, Any]:
    """Requeue only old rows that the correct broker adapter can now measure.

    Every legacy row is considered once. Unrecoverable rows remain account-history
    evidence and receive an explicit marker; no result or cost is fabricated.
    """
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        with closing(connect(db_path)) as conn:
            rows = conn.execute("""SELECT shadow_trade_id,created_at,symbol,strategy,
                    intended_entry,stop_loss,take_profit,intended_broker,asset_type,quantity,
                    simulated_costs_json
                FROM SHADOW_TRADES WHERE outcome_status='unsettleable'
                  AND (benchmark_outcome IS NULL OR benchmark_outcome='')
                ORDER BY created_at LIMIT ?""", (int(limit),)).fetchall()
            parsed: list[tuple[dict[str, Any], Any]] = []
            for raw in rows:
                data = dict(raw) if hasattr(raw, "keys") else dict(zip(
                    ("shadow_trade_id","created_at","symbol","strategy","intended_entry","stop_loss",
                     "take_profit","intended_broker","asset_type","quantity","simulated_costs_json"), raw))
                try:
                    trade = adapter_for(data["intended_broker"]).normalize(data)
                except ValueError:
                    trade = None
                parsed.append((data, trade))
            starts = [_parse_stamp(data.get("created_at")) for data, trade in parsed if trade]
            starts = [value for value in starts if value]
            candles = _load_candles(conn, {(trade.asset_class, trade.market_symbol)
                for _data, trade in parsed if trade}, start_at=min(starts) if starts else None,
                end_at=moment)
            requeue, retain = [], []
            for data, trade in parsed:
                created = _parse_stamp(data.get("created_at"))
                has_follow_up = bool(trade and created and _window(
                    candles.get((trade.asset_class, trade.market_symbol), []),
                    created, created + timedelta(days=SHADOW_HORIZON_DAYS)))
                (requeue if has_follow_up else retain).append(data["shadow_trade_id"])
            with conn:
                if requeue:
                    conn.executemany("""UPDATE SHADOW_TRADES SET outcome_status='pending',updated_at=?,
                        benchmark_outcome=? WHERE shadow_trade_id=? AND outcome_status='unsettleable'""",
                        [(moment.isoformat(), f"schema:v{SETTLEMENT_SCHEMA_VERSION}:legacy_requeued", sid)
                         for sid in requeue])
                if retain:
                    conn.executemany("""UPDATE SHADOW_TRADES SET updated_at=?,benchmark_outcome=?
                        WHERE shadow_trade_id=? AND outcome_status='unsettleable'""",
                        [(moment.isoformat(), f"schema:v{SETTLEMENT_SCHEMA_VERSION}:legacy_unrecoverable", sid)
                         for sid in retain])
        return {"checked": len(rows), "requeued": len(requeue), "retained_unrecoverable": len(retain)}
    except Exception as exc:  # reconciliation is evidence repair, never a trading dependency
        return {"status": "unavailable", "reason": f"{type(exc).__name__}: {exc}"}


def _note_unsettleable(bucket: list[Any], shadow_trade_id: Any, created: Any, moment: Any) -> None:
    """Queue a shadow trade for retirement, but only once it is genuinely beyond saving.

    The grace period matters. A missing candle can be temporary -- a feed outage, a symbol not
    yet backfilled -- and retiring on the first failed attempt would throw away trades that
    would have settled fine a day later. Only rows already past the horizon PLUS the grace
    window are retired, by which point no further candle is going to arrive to settle them.
    """

    if created is None:
        bucket.append(shadow_trade_id)
        return
    if created < moment - timedelta(days=SHADOW_HORIZON_DAYS + SHADOW_SETTLE_GRACE_DAYS):
        bucket.append(shadow_trade_id)


def _settled_shadow_values(db_path: Path, *, window_days: int = 45) -> dict[tuple[str, str], list[float]]:
    """Settled shadow results in the window, keyed (strategy, symbol), as raw values.

    2026-09-06 Supabase egress finding. shadow_strategy_records and shadow_symbol_records each
    read the WHOLE settled table -- 1,490 rows, 287 times a day apiece -- and then discarded
    everything outside the window in Python. Two full reads of identical data, about 200 MB a
    day, on an account already restricted for exceeding its quota.

    Raw values rather than summaries because shadow_strategy_records recombines these buckets:
    the (strategy, symbol) groups partition the per-strategy ones, so concatenating raw values
    reproduces the old result exactly, while recombining rounded expectancies would not.

    THE DATE FILTER IS COARSE ON PURPOSE, and the precise check stays in Python below. This
    column holds ISO strings for most rows and Kraken epoch floats for others -- the same
    two-formats-in-one-column trap already fixed in BROKER_TRADE_HISTORY and
    PERFORMANCE_ATTRIBUTION -- and '1787162315.152785' sorts before '2026-07-23' as text. So
    SQL narrows the ISO-dated majority and _parse_stamp still decides. Filtering entirely in
    SQL would silently drop every epoch-dated row; filtering entirely in Python is what this
    commit is fixing.
    """

    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    grouped: dict[tuple[str, str], list[float]] = {}
    try:
        with closing(connect(db_path)) as conn:
            rows = conn.execute(
                """
                SELECT strategy, symbol, estimated_net_r, created_at FROM SHADOW_TRADES
                WHERE outcome_status <> 'pending' AND estimated_net_r IS NOT NULL
                  AND (created_at >= ? OR created_at NOT LIKE ?)
                """,
                (cutoff.isoformat(), "2%"),
            ).fetchall()
    except Exception:  # noqa: BLE001 - a missing table or column must not break the scoreboard
        return {}
    for row in rows:
        stamp = _parse_stamp(row[3])
        if stamp is not None and stamp < cutoff:
            continue
        strategy = str(row[0] or "").strip()
        symbol = str(row[1] or "").strip().upper()
        value = _as_float(row[2])
        if strategy and symbol and value is not None:
            grouped.setdefault((strategy, symbol), []).append(value)
    return grouped


def shadow_strategy_records(db_path: Path, *, window_days: int = 45) -> dict[str, dict[str, Any]]:
    """Per-strategy results from settled shadow trades.

    This is what lets a demoted strategy earn its permission back without risking money. It is
    deliberately kept separate from `strategy_performance.strategy_records`, which reads real
    money only: a shadow result is a simulation and must never be presented as, or silently
    mixed into, an actual trading record.
    """
    # 2026-09-06 Supabase egress finding: this and shadow_symbol_records below were TWO full
    # reads of the same 1,490-row table, 287 times a day each, together about 200 MB/day on an
    # account already restricted for exceeding its quota. They are the same rows grouped
    # differently, so they now share one read and this one aggregates the finer grouping.
    #
    # Mathematically identical, not an approximation: the per-(strategy, symbol) buckets are a
    # partition of the per-strategy ones, so concatenating the raw values back together gives
    # exactly the list this function used to build itself. Recombining the ROUNDED summaries
    # would not, which is why _settled_shadow_values returns raw values.
    grouped: dict[str, list[float]] = {}
    for (strategy, _symbol), values in _settled_shadow_values(db_path, window_days=window_days).items():
        grouped.setdefault(strategy, []).extend(values)
    return {
        strategy: {
            "sample_size": len(values),
            "expectancy_r": round(sum(values) / len(values), 4),
            "win_rate": round(sum(1 for v in values if v > 0) / len(values), 4),
            "basis": "shadow_simulation",
        }
        for strategy, values in grouped.items()
    }


def shadow_symbol_records(db_path: Path, *, window_days: int = 45) -> dict[tuple[str, str], dict[str, Any]]:
    """Settled shadow results split by strategy AND coin, keyed (strategy, symbol).

    This is where the per-coin picture actually has coverage. Real money gives at most a dozen
    closed trades for any one strategy/coin pair -- too thin to judge -- while settled shadow
    trades give hundreds. Measured 2026-09-05: crypto_trend_following_2r ran -0.15R on BCH over
    43 candidates against -1.77R on XRP over 165, which is the spread that makes judging the
    strategy on its average wrong.
    """
    grouped = _settled_shadow_values(db_path, window_days=window_days)
    return {
        key: {
            "sample_size": len(values),
            "expectancy_r": round(sum(values) / len(values), 4),
            "win_rate": round(sum(1 for v in values if v > 0) / len(values), 4),
            "basis": "shadow_simulation",
        }
        for key, values in grouped.items()
    }


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
