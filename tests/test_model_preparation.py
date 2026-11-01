import errno
import json
import sys
import time

import pytest
from fastapi.testclient import TestClient
from meetinglog.app import create_app
from meetinglog.db import ApiError
from meetinglog.domain import StageRequest
from meetinglog.jobs.runner import Worker

ORIGIN = {"Origin": "http://localhost:8765"}


@pytest.mark.parametrize(
    "error,code",
    [
        (PermissionError("private-download-token"), "model_storage_permission"),
        (OSError(errno.ENOSPC, "private-download-token"), "model_storage_full"),
        (ApiError("model_not_ready", "private-download-token"), "model_validation_failed"),
    ],
)
def test_download_errors_report_known_reason_without_exposing_paths(
    settings, tmp_path, monkeypatch, error, code
):
    from meetinglog.engines.local_executor import execute
    from meetinglog.engines.models import ModelRegistry

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(ModelRegistry, "prepare", fail)
    request = StageRequest(
        job_id="model",
        recording_id="",
        generation=0,
        stage="models",
        input_path="",
        output_path=str(tmp_path / "result.json"),
        mode="local_only",
        model_name="vad",
    )
    with pytest.raises(ApiError) as caught:
        execute(request, settings)
    assert caught.value.code == code
    assert "private-download-token" not in caught.value.message
    assert str(tmp_path) not in caught.value.message


def wait_for(client, state):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        response = client.get("/api/settings/models/download")
        assert response.status_code == 200
        result = response.json()
        if result["state"] == state:
            return result
        time.sleep(0.03)
    raise AssertionError(f"Expected {state}, got {result}")


def model_command(settings, gate, fail=False):
    def command(request):
        script = f"""
import json, os, sys, time
from pathlib import Path
assert os.environ['HF_HUB_OFFLINE'] == '0'
output = Path(sys.argv[1])
events = output.with_suffix('.events.jsonl')
events.write_text(json.dumps({{'event':'model_progress','phase':'downloading','completed':1,'total':2}})+'\\n')
while not Path({str(gate)!r}).exists(): time.sleep(.02)
if {fail!r}:
    print('private-download-token', file=sys.stderr)
    sys.exit(1)
root = Path({str(settings.models_dir)!r})
directory = root / 'vad'
directory.mkdir(parents=True, exist_ok=True)
(directory/'config.json').write_text('{{}}')
(directory/'model.safetensors').write_bytes(b'weights')
(root/'manifest.json').write_text(json.dumps({{'schema_version':1,'models':{{'vad':{{'repo_id':{settings.vad_repo!r},'revision':'test','path':'vad','files':{{'config.json':2,'model.safetensors':7}}}}}}}}))
output.write_text(json.dumps({{'model':'vad'}}))
"""
        return [sys.executable, "-c", script, request.output_path]

    return command


def test_settings_download_progress_completion_and_origin_boundary(settings, db, tmp_path):
    settings.ollama_url = "http://127.0.0.1:1"
    app = create_app(settings)
    gate = tmp_path / "finish"
    with TestClient(app, base_url="http://localhost:8765") as client:
        assert client.get("/api/settings/models/download").status_code == 200
        for name, headers, body, status in [
            ("vad", {}, {}, 403),
            ("unknown", ORIGIN, {}, 422),
            ("vad", ORIGIN, {"url": "https://example.com/model"}, 422),
        ]:
            assert (
                client.post(
                    f"/api/settings/models/{name}/download", headers=headers, json=body
                ).status_code
                == status
            )
        app.state.model_preparation.command = model_command(settings, gate)
        started = client.post("/api/settings/models/vad/download", headers=ORIGIN, json={})
        assert started.status_code == 200
        downloading = wait_for(client, "downloading")
        assert downloading["model"] == "vad"
        assert (downloading["completed"], downloading["total"]) == (1, 2)
        assert (
            client.post("/api/settings/models/vad/download", headers=ORIGIN, json={}).status_code
            == 200
        )
        assert (
            client.post("/api/settings/models/asr/download", headers=ORIGIN, json={}).status_code
            == 409
        )
        gate.touch()
        assert wait_for(client, "succeeded")["error_message"] is None
        readiness = client.get("/api/settings").json()
        assert (
            next(model for model in readiness["engines"] if model["name"] == "vad")["ready"] is True
        )


def test_download_failure_is_safe_and_can_be_retried(settings, db, tmp_path):
    settings.ollama_url = "http://127.0.0.1:1"
    app = create_app(settings)
    gate = tmp_path / "finish"
    gate.touch()
    with TestClient(app, base_url="http://localhost:8765") as client:
        app.state.model_preparation.command = model_command(settings, gate, fail=True)
        assert (
            client.post("/api/settings/models/vad/download", headers=ORIGIN, json={}).status_code
            == 200
        )
        failed = wait_for(client, "failed")
        assert failed["error_message"]
        assert "private-download-token" not in json.dumps(failed)
        assert str(settings.data_dir) not in json.dumps(failed)
        app.state.model_preparation.command = model_command(settings, gate)
        assert (
            client.post("/api/settings/models/vad/download", headers=ORIGIN, json={}).status_code
            == 200
        )
        wait_for(client, "succeeded")


def test_worker_status_checks_live_lock_not_stale_file(settings, db):
    settings.ollama_url = "http://127.0.0.1:1"
    with TestClient(create_app(settings), base_url="http://localhost:8765") as client:
        assert client.get("/api/settings").json()["worker_running"] is False
        with Worker(settings, db):
            assert client.get("/api/settings").json()["worker_running"] is True
        assert (settings.data_dir / "worker.lock").exists()
        assert client.get("/api/settings").json()["worker_running"] is False


def test_server_close_stops_download_and_releases_inference_lock(settings, tmp_path):
    from meetinglog.jobs.locks import inference_lock

    settings.ollama_url = "http://127.0.0.1:1"
    app = create_app(settings)
    with TestClient(app, base_url="http://localhost:8765") as client:
        app.state.model_preparation.command = model_command(settings, tmp_path / "never-finish")
        client.post("/api/settings/models/vad/download", headers=ORIGIN, json={})
        wait_for(client, "downloading")
    assert app.state.model_preparation.status().state == "failed"
    with inference_lock(settings, exclusive=True, blocking=False):
        pass
