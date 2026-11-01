from tests.api_fixtures import populated_client


def test_upload_limits_expose_server_configuration(settings):
    from fastapi.testclient import TestClient
    from meetinglog.app import create_app

    with TestClient(create_app(settings), base_url="http://localhost:8765") as client:
        assert client.get("/api/recordings/limits").json() == {
            "max_upload_bytes": 2_000_000_000,
            "max_duration_ms": 7_200_000,
        }
        settings.max_upload_bytes = 500_000_000
        assert client.get("/api/recordings/limits").json() == {
            "max_upload_bytes": 500_000_000,
            "max_duration_ms": 7_200_000,
        }


def test_alac_upload_plays_as_wav_without_changing_original(settings, db, tmp_path):
    import io
    import subprocess
    import wave
    from pathlib import Path

    from fastapi.testclient import TestClient
    from meetinglog.app import create_app

    from tests.audio_fixtures import write_silence

    source = write_silence(tmp_path / "source.wav", rate=48000, channels=2)
    alac = tmp_path / "recording.m4a"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(source), "-c:a", "alac", str(alac)], check=True
    )
    original = alac.read_bytes()
    with TestClient(create_app(settings), base_url="http://localhost:8765") as client:
        response = client.post(
            "/api/recordings", files={"file": (alac.name, original, "audio/mp4")}
        )
        assert response.status_code == 201
        recording_id = response.json()["id"]
        playback = client.get(f"/api/recordings/{recording_id}/audio")
        assert playback.status_code == 200
        assert playback.headers["content-type"] == "audio/wav"
        with wave.open(io.BytesIO(playback.content)) as audio:
            assert (audio.getframerate(), audio.getnchannels(), audio.getnframes()) == (
                48000,
                2,
                48000,
            )
        with db.session() as connection:
            path = connection.execute(
                "SELECT original_path FROM recordings WHERE id=?", (recording_id,)
            ).fetchone()[0]
        assert Path(path).read_bytes() == original
        assert client.get(f"/api/recordings/{recording_id}/audio").content == playback.content
        partial = client.get(
            f"/api/recordings/{recording_id}/audio", headers={"Range": "bytes=0-15"}
        )
        assert partial.status_code == 206
        assert partial.content == playback.content[:16]


def test_browser_recording_audio_has_duration_and_preserves_encoded_audio(settings, db, tmp_path):
    import json
    import subprocess
    from pathlib import Path

    from fastapi.testclient import TestClient
    from meetinglog.app import create_app

    source = Path(__file__).parent / "fixtures" / "browser-fake-mic.webm"
    original = source.read_bytes()
    with TestClient(create_app(settings), base_url="http://localhost:8765") as client:
        recording_id = client.post("/api/recordings/drafts", json={"title": "녹음"}).json()["id"]
        assert (
            client.put(f"/api/recordings/{recording_id}/chunks/0", content=original).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/recordings/{recording_id}/finalize", json={"last_sequence": 0}
            ).status_code
            == 200
        )
        response = client.get(f"/api/recordings/{recording_id}/audio")
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/webm"
        playback = tmp_path / "playback.webm"
        playback.write_bytes(response.content)

        def metadata(path):
            return json.loads(
                subprocess.check_output(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_packets",
                        "-show_data_hash",
                        "sha256",
                        "-show_entries",
                        "format=duration:stream=codec_name,sample_rate,channels:packet=data_hash",
                        "-of",
                        "json",
                        str(path),
                    ]
                )
            )

        encoded, served = metadata(source), metadata(playback)
        assert 1 <= float(served["format"].get("duration", 0)) <= 1.5
        assert served["streams"] == encoded["streams"]
        assert served["packets"] == encoded["packets"]
        with db.session() as connection:
            stored = connection.execute(
                "SELECT original_path FROM recordings WHERE id=?", (recording_id,)
            ).fetchone()
        assert Path(stored["original_path"]).read_bytes() == original
        assert client.get(f"/api/recordings/{recording_id}/audio").content == response.content
        partial = client.get(
            f"/api/recordings/{recording_id}/audio", headers={"range": "bytes=0-15"}
        )
        assert partial.status_code == 206
        assert partial.content == response.content[:16]


def test_recording_list_detail_and_audio_range(settings, db, tmp_path):
    client, record_id, transcript = populated_client(settings, db, tmp_path)
    try:
        listed = client.get("/api/recordings").json()
        assert listed["items"][0]["id"] == record_id
        detail = client.get(f"/api/recordings/{record_id}").json()
        assert detail["transcript"]["id"] == transcript.id
        audio = client.get(f"/api/recordings/{record_id}/audio", headers={"range": "bytes=0-9"})
        assert audio.status_code == 206
        assert len(audio.content) == 10
        assert audio.headers["content-range"].startswith("bytes 0-9/")
        assert (
            client.get(
                f"/api/recordings/{record_id}/audio", headers={"range": "bytes=9999999-"}
            ).status_code
            == 416
        )
    finally:
        client.__exit__(None, None, None)


def test_duplicate_finalize_does_not_create_second_initial_job(settings, db, tmp_path):
    from fastapi.testclient import TestClient
    from meetinglog.app import create_app
    from meetinglog.jobs.repository import JobRepository

    from tests.audio_fixtures import write_silence

    with TestClient(create_app(settings), base_url="http://localhost:8765") as client:
        record_id = client.post("/api/recordings/drafts", json={"title": "녹음"}).json()["id"]
        audio = write_silence(tmp_path / "draft.wav").read_bytes()
        assert client.put(f"/api/recordings/{record_id}/chunks/0", content=audio).status_code == 200
        assert (
            client.post(
                f"/api/recordings/{record_id}/finalize", json={"last_sequence": 0}
            ).status_code
            == 200
        )
        repo = JobRepository(db)
        job = repo.claim()
        repo.finish(job.id, "succeeded")
        assert (
            client.post(
                f"/api/recordings/{record_id}/finalize", json={"last_sequence": 0}
            ).status_code
            == 200
        )
        with db.session() as connection:
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM jobs WHERE recording_id=?", (record_id,)
                ).fetchone()[0]
                == 1
            )


def test_edit_marks_analysis_stale_and_exports_do_not_mix_versions(settings, db, tmp_path):

    from meetinglog.analysis.service import AnalysisService
    from meetinglog.domain import AnalysisVersion, new_id
    from meetinglog.jobs.repository import JobRepository

    from tests.analysis_fixtures import analysis_fixture

    client, record_id, transcript = populated_client(settings, db, tmp_path)
    try:
        response = client.post(
            f"/api/recordings/{record_id}/analyze",
            json={"mode": "local_only", "transcript_id": transcript.id, "form": "meeting"},
        )
        assert response.status_code == 200
        repo = JobRepository(db)
        job = repo.claim()
        version = AnalysisVersion(
            id=new_id(),
            transcript_id=transcript.id,
            body=analysis_fixture(),
            provider="test",
            model="fixed",
            prompt_version="1",
        )
        artifact = tmp_path / "analysis.json"
        artifact.write_text(version.model_dump_json())
        AnalysisService(db).publish(job, artifact)
        repo.finish(job.id, "succeeded")
        edited = client.patch(
            f"/api/recordings/{record_id}/transcript",
            json={
                "base_version_id": transcript.id,
                "changes": [{"turn_id": "t2", "text": "이번 주에 시작합니다."}],
            },
        )
        assert edited.status_code == 200
        assert client.get(f"/api/recordings/{record_id}").json()["analysis_stale"] is True
        assert client.get(f"/api/recordings/{record_id}/export").json()["analysis"] is None
        markdown = client.get(f"/api/recordings/{record_id}/export?format=markdown").text
        assert edited.json()["id"] in markdown
        assert version.id not in markdown
        assert "서비스 시작 일정을 논의했다." not in markdown
        assert (
            client.get(f"/api/recordings/{record_id}/export?format=analysis_markdown").status_code
            == 409
        )
        summary = client.get(
            f"/api/recordings/{record_id}/export?format=analysis_markdown"
            f"&transcript_id={transcript.id}&analysis_id={version.id}"
        )
        assert summary.status_code == 200
        assert "서비스 시작 일정을 논의했다." in summary.text
        assert "이번 주에 시작합니다." not in summary.text
        assert (
            client.get(f"/api/recordings/{record_id}/export?analysis_id={version.id}").status_code
            == 409
        )
    finally:
        client.__exit__(None, None, None)
