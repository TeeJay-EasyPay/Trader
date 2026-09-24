"""Bounded, value-free DB transfer estimates.

Counts consumed row values, not TLS/protocol/billed bytes. Unfetched rows and
server/platform traffic are outside this measurement. Local hourly aggregation
survives job subprocesses; compact logs make worker results remotely retrievable.
Telemetry failure must never change a database result or mask its exception.
Worker publishes one bounded summary per hour; no per-query database writes.
"""
import atexit
import json
import os
import re
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from functools import lru_cache

_lock = threading.Lock()
_pending = {}
_last_flush = time.monotonic()
_started = time.monotonic()
MAX_FAMILIES = 64
DEFAULT_DAILY_ROW_VALUE_BUDGET = 150 * 1024 * 1024
DEFAULT_FAMILY_ROW_VALUE_BUDGET = 40 * 1024 * 1024


def family(sql):
    text = str(sql)
    # Store only a coarse, allowlisted identifier, never SQL or parameters.
    match = re.search(r'\b(?:FROM|INTO|UPDATE)\s+([a-zA-Z_][a-zA-Z_0-9.]*)', text, re.I)
    table = match.group(1).lower()[:64] if match else "other"
    operation = text.lstrip().split(None, 1)[0].upper() if text.strip() else "OTHER"
    if operation not in {"SELECT", "WITH", "INSERT", "UPDATE", "DELETE", "SET", "BEGIN", "COMMIT", "ROLLBACK"}:
        operation = "OTHER"
    return operation + ":" + table


def size(value):
    if value is None:
        return 0
    if isinstance(value, (bytes, bytearray, memoryview)):
        return len(value)
    if isinstance(value, dict):
        return len(json.dumps(value,default=str,separators=(",",":")).encode("utf-8"))
    if isinstance(value, (list, tuple)):
        return sum(size(v) for v in value)
    return len(str(value).encode("utf-8"))


def record(label, **values):
    global _last_flush
    try:
        if os.getenv("AI_TRADER_DB_TELEMETRY", "1") == "0":
            return
        with _lock:
            if label not in _pending and len(_pending) >= MAX_FAMILIES:
                label = "other"
            item = _pending.setdefault(label, {})
            for key, value in values.items():
                item[key] = item.get(key, 0) + value
        if time.monotonic() - _last_flush >= 300:
            flush()
    except Exception:
        pass


def local_path():
    return Path(tempfile.gettempdir()) / "ai-trader-db-telemetry.sqlite3"


def flush():
    global _last_flush
    try:
        with _lock:
            if not _pending:
                return
            batch = dict(_pending)
            _pending.clear()
            _last_flush = time.monotonic()
        from .database import postgres_application_name
        role = postgres_application_name()
        revision = os.getenv("RENDER_GIT_COMMIT", "local")[:40]
        hour = time.strftime("%Y-%m-%dT%H:00:00Z", time.gmtime())
        # Counts only. Limit disk history and per-process cardinality.
        with sqlite3.connect(local_path(), timeout=.1) as db:
            if os.name != "nt":
                local_path().chmod(0o600)
            db.execute("CREATE TABLE IF NOT EXISTS usage(hour TEXT,role TEXT,revision TEXT,family TEXT,counts TEXT,PRIMARY KEY(hour,role,revision,family))")
            for label, counts in batch.items():
                key = (hour, role, revision, label)
                old = db.execute("SELECT counts FROM usage WHERE hour=? AND role=? AND revision=? AND family=?", key).fetchone()
                merged = json.loads(old[0]) if old else {}
                for k,v in counts.items():
                    merged[k] = merged.get(k, 0) + v
                db.execute("INSERT OR REPLACE INTO usage VALUES(?,?,?,?,?)", (*key,json.dumps(merged)))
            db.execute("DELETE FROM usage WHERE hour < strftime('%Y-%m-%dT%H:00:00Z','now','-8 days')")
        totals = {}
        for counts in batch.values():
            for k,v in counts.items():
                totals[k] = totals.get(k,0) + v
        top = sorted(batch.items(),key=lambda x:x[1].get("row_bytes",0),reverse=True)[:8]
        print("[db-transfer] " + json.dumps(dict(hour=hour,role=role,revision=revision,
            pid=os.getpid(),process_seconds=round(time.monotonic()-_started),
            metric="consumed_value_bytes_not_billed_egress",totals=totals,top=top),separators=(",",":")),flush=True)
    except Exception:
        # Monitoring is best effort, never part of trading correctness.
        pass


atexit.register(flush)


def report():
    """Host-local last three UTC days; explicitly incomplete wire accounting."""
    from collections import Counter, defaultdict
    days = defaultdict(Counter)
    labels = defaultdict(Counter)
    roles = defaultdict(Counter)
    try:
        flush()
        with sqlite3.connect(local_path(),timeout=.1) as db:
            rows=db.execute("SELECT hour,role,family,counts FROM usage WHERE hour >= strftime('%Y-%m-%d','now','-2 days')").fetchall()
        for hour,role,label,raw in rows:
            counts=json.loads(raw)
            days[hour[:10]].update(counts)
            labels[label].update(counts)
            roles[role].update(counts)
        day_map = dict(days)
        latest_day = sorted(day_map)[-1] if day_map else None
        daily_budget = int(os.getenv("AI_TRADER_DB_DAILY_VALUE_BUDGET_BYTES", DEFAULT_DAILY_ROW_VALUE_BUDGET))
        family_budget = int(os.getenv("AI_TRADER_DB_FAMILY_VALUE_BUDGET_BYTES", DEFAULT_FAMILY_ROW_VALUE_BUDGET))
        family_breaches = [dict(family=name, row_bytes=counts.get("row_bytes", 0))
                           for name, counts in labels.items()
                           if counts.get("row_bytes", 0) > family_budget]
        current_bytes = day_map.get(latest_day, {}).get("row_bytes", 0) if latest_day else 0
        return dict(metric="consumed_value_bytes_not_billed_egress",
                    generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
                    days=day_map,
                    top_families=sorted(labels.items(),key=lambda x:x[1].get("row_bytes",0),reverse=True)[:12],
                    top_roles=sorted(roles.items(),key=lambda x:x[1].get("row_bytes",0),reverse=True)[:12],
                    top_errors=sorted(((k,v) for k,v in labels.items() if v.get("errors")),
                                      key=lambda x:x[1]["errors"],reverse=True)[:8],
                    budget=dict(day=latest_day, measured_row_bytes=current_bytes,
                                daily_row_value_budget_bytes=daily_budget,
                                status="over_budget" if current_bytes > daily_budget else "within_budget",
                                family_row_value_budget_bytes=family_budget,
                                family_breaches=sorted(family_breaches,key=lambda x:x["row_bytes"],reverse=True)),
                    provider_egress=None,
                    limitations="Host-local consumed values; excludes protocol, unfetched rows, killed-process buffers and platform traffic. First day is partial.")
    except Exception:
        return {"status":"unavailable","provider_egress":None}


def publish(db_path):
    """A worker tick exports its host metrics; max one small write per hour."""
    try:
        if os.getenv("AI_TRADER_DB_TELEMETRY","1")=="0":
            return
        hour=time.strftime("%Y-%m-%dT%H",time.gmtime())
        with sqlite3.connect(local_path(),timeout=.1) as local:
            local.execute("CREATE TABLE IF NOT EXISTS exports(id INTEGER PRIMARY KEY,hour TEXT)")
            previous=local.execute("SELECT hour FROM exports WHERE id=1").fetchone()
        if previous and previous[0]==hour:
            return
        payload=report()
        encoded=json.dumps(payload,default=str)
        if len(encoded.encode())>24000 or payload.get("status")=="unavailable":
            return
        from . import experiments as exp
        with exp.transaction(db_path) as conn:
            exp.put_control(conn,"db_transfer_view",payload)
        with sqlite3.connect(local_path(),timeout=.1) as local:
            local.execute("INSERT OR REPLACE INTO exports VALUES(1,?)",(hour,))
    except Exception:
        pass


@lru_cache(maxsize=1)
def cursor_factory():
    from psycopg import Cursor
    class MeasuredCursor(Cursor):
        def execute(self, query, params=None, **kwargs):
            self._meter_family = family(query)
            start = time.monotonic()
            try:
                result = super().execute(query, params, **kwargs)
            except Exception as exc:
                code=getattr(exc,"sqlstate",None) or "unknown"
                record(self._meter_family, calls=1, errors=1, **{"errors_"+code:1})
                raise
            record(self._meter_family, calls=1, sql_ms=round((time.monotonic()-start)*1000))
            return result

        def executemany(self, query, params_seq, **kwargs):
            self._meter_family = family(query)
            start = time.monotonic()
            try:
                result = super().executemany(query, params_seq, **kwargs)
            except Exception as exc:
                code=getattr(exc,"sqlstate",None) or "unknown"
                record(self._meter_family, batches=1, errors=1, **{"errors_"+code:1})
                raise
            record(self._meter_family, batches=1, sql_ms=round((time.monotonic()-start)*1000))
            return result

        def _measure(self, rows):
            try:
                if os.getenv("AI_TRADER_DB_TELEMETRY","1")=="0":
                    return
                record(getattr(self,"_meter_family","other"),rows=len(rows),
                       row_bytes=sum(sum(size(v) for v in (r.values() if isinstance(r,dict) else r)) for r in rows))
            except Exception:
                pass

        def fetchone(self):
            row = super().fetchone()
            if row is not None:
                self._measure([row])
            return row

        def fetchmany(self, size=0):
            rows = super().fetchmany(size)
            self._measure(rows)
            return rows

        def fetchall(self):
            rows = super().fetchall()
            self._measure(rows)
            return rows

        def __next__(self):
            row = super().__next__()
            self._measure([row])
            return row
    return MeasuredCursor
