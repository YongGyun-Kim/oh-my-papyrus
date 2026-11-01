import json

import pytest
from meetinglog.db import ApiError


def test_missing_model_fails_without_downloading(settings, monkeypatch):
    from meetinglog.engines.models import ModelRegistry

    def forbidden(*args, **kwargs):
        raise AssertionError("processing must never download a model")

    import huggingface_hub

    monkeypatch.setattr(huggingface_hub, "snapshot_download", forbidden)
    with pytest.raises(ApiError) as error:
        ModelRegistry(settings).require("asr")
    assert error.value.code == "model_not_ready"
    assert not settings.models_dir.exists()


def test_manifest_detects_missing_or_corrupt_weights(settings):
    from meetinglog.engines.models import ModelRegistry

    directory = settings.models_dir / "asr"
    directory.mkdir(parents=True)
    (directory / "config.json").write_text("{}")
    (directory / "model.safetensors").write_bytes(b"weights")
    manifest = {
        "schema_version": 1,
        "models": {
            "asr": {
                "repo_id": settings.asr_repo,
                "revision": "test-revision",
                "path": "asr",
                "files": {"config.json": 2, "model.safetensors": 7},
            }
        },
    }
    (settings.models_dir / "manifest.json").write_text(json.dumps(manifest))
    assert ModelRegistry(settings).require("asr") == directory.resolve()
    (directory / "model.safetensors").write_bytes(b"")
    with pytest.raises(ApiError):
        ModelRegistry(settings).require("asr")


def test_model_prepare_reports_completed_files_and_invalidates_failed_replacement(
    settings, monkeypatch
):
    from types import SimpleNamespace

    import huggingface_hub
    from meetinglog.engines.models import ModelRegistry

    registry = ModelRegistry(settings)
    fail = False

    def download(repo, **kwargs):
        assert kwargs["force_download"] is True
        directory = kwargs["local_dir"]
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "config.json").write_text("{}")
        (directory / "model.safetensors").write_bytes(b"weights")
        with kwargs["tqdm_class"](total=2) as progress:
            progress.update(1)
            progress.refresh()
            progress.update(1)
            progress.refresh()
        if fail:
            raise RuntimeError("private-download-token")

    monkeypatch.setattr(
        huggingface_hub,
        "HfApi",
        lambda: SimpleNamespace(model_info=lambda repo: SimpleNamespace(sha="revision")),
    )
    monkeypatch.setattr(huggingface_hub, "snapshot_download", download)
    updates = []
    registry.prepare(
        ["vad"], progress=lambda done, total: updates.append((done, total)), force_download=True
    )
    assert (0, 2) in updates and (1, 2) in updates and (2, 2) in updates
    assert registry.require("vad").is_dir()
    (settings.models_dir / "vad/model.safetensors").write_bytes(b"truncated")
    registry.prepare(["vad"], progress=lambda *_: None)
    fail = True
    with pytest.raises(RuntimeError):
        registry.prepare(["vad"], progress=lambda *_: None, force_download=True)
    with pytest.raises(ApiError):
        registry.require("vad")
