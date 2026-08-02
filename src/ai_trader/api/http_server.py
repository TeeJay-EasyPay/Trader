from __future__ import annotations

import hmac
import json
import logging
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler
from threading import Lock
from typing import Any
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger("ai_trader.api")


class ApiHandler(BaseHTTPRequestHandler):
    service: LocalApiService
    api_token: str | None = None
    hosted_read_only: bool = False

    _auth_failures: dict[str, deque] = defaultdict(deque)
    _lockout_until: dict[str, float] = {}
    _auth_lock = Lock()
    _MAX_AUTH_FAILURES = 10
    _AUTH_FAILURE_WINDOW_SECONDS = 60
    _LOCKOUT_SECONDS = 300

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if not self._authorized(parsed.path):
                self._json(401, {"error": "unauthorized"})
                return
            status, payload = self.service.get(parsed.path, parse_qs(parsed.query))
            self._json(status, payload)
        except Exception as exc:
            self._json(500, {"error": "internal_error", "message": str(exc), "path": parsed.path})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if not self._authorized(parsed.path):
                self._json(401, {"error": "unauthorized"})
                return
            if self.hosted_read_only:
                self._json(
                    403,
                    {
                        "error": "hosted_read_only",
                        "message": (
                            "Hosted API is running without AI_TRADER_API_TOKEN, so POST commands are disabled. "
                            "Set AI_TRADER_API_TOKEN in Render to enable trading/control actions."
                        ),
                    },
                )
                return
            body = self._read_body()
            status, payload = self.service.post(parsed.path, body)
            self._json(status, payload)
        except Exception as exc:
            self._json(500, {"error": "internal_error", "message": str(exc), "path": parsed.path})

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("POST body must be a JSON object")
        return data

    def _client_ip(self) -> str:
        address = getattr(self, "client_address", None)
        return address[0] if address else "unknown"

    def _is_locked_out(self, ip: str) -> bool:
        with self._auth_lock:
            until = self._lockout_until.get(ip)
            if until is None:
                return False
            if until > time.time():
                return True
            del self._lockout_until[ip]
            return False

    def _record_auth_failure(self, ip: str) -> None:
        now = time.time()
        with self._auth_lock:
            failures = self._auth_failures[ip]
            failures.append(now)
            while failures and now - failures[0] > self._AUTH_FAILURE_WINDOW_SECONDS:
                failures.popleft()
            if len(failures) >= self._MAX_AUTH_FAILURES:
                self._lockout_until[ip] = now + self._LOCKOUT_SECONDS
                failures.clear()
                logger.warning("Locking out %s for %ss after repeated auth failures.", ip, self._LOCKOUT_SECONDS)

    def _authorized(self, path: str) -> bool:
        if path in {"/healthz"}:
            return True
        ip = self._client_ip()
        if ip != "unknown" and self._is_locked_out(ip):
            return False
        if not self.api_token:
            return True
        auth = self.headers.get("Authorization", "")
        api_key = self.headers.get("X-API-Key", "")
        authorized = hmac.compare_digest(auth, f"Bearer {self.api_token}") or hmac.compare_digest(api_key, self.api_token)
        if not authorized and ip != "unknown":
            self._record_auth_failure(ip)
        return authorized

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        if "html" in payload and len(payload) == 1:
            body = str(payload["html"]).encode("utf-8")
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-API-Key")
