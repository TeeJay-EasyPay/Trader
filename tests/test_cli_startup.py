from __future__ import annotations

from ai_trader import api, cli


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
