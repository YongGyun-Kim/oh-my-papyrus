from fastapi.testclient import TestClient
from meetinglog.app import create_app


def test_mode_persists_across_app_restarts_and_secret_patch_is_rejected(settings):
    settings.ollama_url = "http://127.0.0.1:1"
    with TestClient(create_app(settings), base_url="http://localhost:8765") as client:
        assert client.patch("/api/settings", json={"mode": "auto"}).status_code == 200
        assert (
            client.patch(
                "/api/settings", json={"mode": "api", "openai_api_key": "should-not-be-accepted"}
            ).status_code
            == 422
        )
    with TestClient(create_app(settings), base_url="http://localhost:8765") as client:
        result = client.get("/api/settings")
        assert result.status_code == 200
        assert result.json()["mode"] == "auto"
        assert "openai_api_key" not in result.text


def test_readiness_uses_selected_cli_account_without_requiring_ollama(settings, db, monkeypatch):
    from meetinglog.cli_auth import CliAuth, CliConnection

    with db.session() as connection:
        connection.execute(
            "INSERT INTO settings(key,value) VALUES('analysis',?)",
            ('{"provider":"codex","model":"test-model","reasoning":"default"}',),
        )
    monkeypatch.setattr(
        CliAuth,
        "status",
        lambda self, provider: CliConnection(
            provider=provider, state="connected", auth_method="account"
        ),
    )
    with TestClient(create_app(settings), base_url="http://localhost:8765") as client:
        result = client.get("/api/settings")
        assert result.status_code == 200
        connection = result.json()["analysis_connection"]
        assert connection["provider"] == "codex"
        assert connection["ready"] is True
        assert connection["model"] == "test-model"
        assert all(engine["name"] != "analysis" for engine in result.json()["engines"])
