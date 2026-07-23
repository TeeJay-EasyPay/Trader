from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ai_trader import api, cli
from ai_trader.config import load_settings


def test_serve_api_does_not_eagerly_initialize_audit_database(monkeypatch) -> None:
    calls: list[tuple[str, int, str | None]] = []

    class UnexpectedAuditDatabase:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("serve-api must not initialize the audit database before binding")

    monkeypatch.setattr(cli, "AuditDatabase", UnexpectedAuditDatabase)
    monkeypatch.setattr(
        api,
        "run_server",
        lambda host, port, api_token=None: calls.append((host, port, api_token)),
    )
    monkeypatch.setenv("AI_TRADER_API_HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "9876")
    monkeypatch.setenv("AI_TRADER_API_TOKEN", "test-token")

    result = cli.main(["serve-api"])

    assert result == 0
    assert calls == [("0.0.0.0", 9876, "test-token")]


def test_config_does_not_initialize_audit_database(monkeypatch, capsys) -> None:
    class UnexpectedAuditDatabase:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("config is a read-only command")

    monkeypatch.setattr(cli, "AuditDatabase", UnexpectedAuditDatabase)

    assert cli.main(["config"]) == 0
    assert '"database_backend"' in capsys.readouterr().out


def test_legacy_background_worker_flag_disables_api_workers(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AI_TRADER_DISABLE_API_BACKGROUND_WORKERS", raising=False)
    monkeypatch.setenv("AI_TRADER_DISABLE_BACKGROUND_WORKERS", "true")

    assert load_settings().disable_api_background_workers is True


def test_api_binds_socket_before_service_initialization(monkeypatch, tmp_path) -> None:
    sequence: list[str] = []
    settings = SimpleNamespace(
        output_dir=Path(tmp_path),
        is_hosted_runtime=True,
        disable_api_background_workers=True,
        production_startup_errors=lambda host=None: [],
    )

    class FakeServer:
        def __init__(self, address, handler) -> None:
            sequence.append("socket_bound")

        def serve_forever(self) -> None:
            sequence.append("serving")

    class FakeService:
        def __init__(self, loaded_settings, *, initialize_runtime=True) -> None:
            sequence.append("service_initialized")
            self.settings = loaded_settings
            self.hosted_read_only = False
            self.api_token_configured = False

    monkeypatch.setattr(api, "load_settings", lambda: settings)
    monkeypatch.setattr(api, "configure_logging", lambda output_dir: None)
    monkeypatch.setattr(api, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(api, "LocalApiService", FakeService)

    api.run_server("0.0.0.0", 9876, api_token="test-token")

    assert sequence == ["socket_bound", "service_initialized", "serving"]
