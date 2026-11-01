import pytest
from meetinglog.db import ApiError
from meetinglog.domain import StageResult

from tests.audio_fixtures import write_silence


@pytest.fixture
def jobs(input_service, db, tmp_path):
    from meetinglog.jobs.repository import JobRepository

    record = input_service.import_file(
        "ready.wav", [write_silence(tmp_path / "ready.wav").read_bytes()]
    )
    return JobRepository(db), record


def test_cancelled_job_cannot_publish_and_active_enqueue_is_idempotent(jobs):
    repository, recording = jobs
    job = repository.enqueue(recording.id, "process", None, "local_only")
    assert repository.enqueue(recording.id, "process", None, "local_only").id == job.id
    assert repository.claim().id == job.id
    repository.cancel(job.id)
    result = StageResult(
        job_id=job.id, generation=job.generation, stage="speech", artifact_path="speech.json"
    )
    assert repository.commit_stage(result) is False


def test_recovery_retains_completed_checkpoint(jobs):
    repository, recording = jobs
    job = repository.enqueue(recording.id, "process", None, "local_only")
    repository.claim()
    assert repository.commit_stage(
        StageResult(job_id=job.id, generation=0, stage="speech", artifact_path="speech.json")
    )
    repository.recover()
    recovered = repository.claim()
    assert recovered.id == job.id
    assert recovered.stage == "analysis"


def test_second_worker_cannot_modify_running_job(jobs, settings):
    from meetinglog.jobs.runner import Worker

    repository, recording = jobs
    repository.enqueue(recording.id, "process", None, "local_only")
    with Worker(settings, repository.db):
        running = repository.claim()
        with pytest.raises(ApiError) as error:
            with Worker(settings, repository.db):
                pass
        assert error.value.code == "worker_running"
        assert repository.get(running.id).state == "running"


def test_model_preparation_keeps_jobs_queued_until_its_lock_is_released(jobs, settings):
    from meetinglog.jobs.locks import inference_lock
    from meetinglog.jobs.runner import Worker

    repository, recording = jobs
    job = repository.enqueue(recording.id, "process", None, "local_only")
    with Worker(settings, repository.db) as worker:
        with inference_lock(settings, exclusive=True):
            assert worker.run_once() is False
            assert repository.get(job.id).state == "queued"
        assert repository.claim().id == job.id


def test_deleted_generation_rejects_late_stage(jobs):
    repository, recording = jobs
    job = repository.enqueue(recording.id, "process", None, "local_only")
    repository.claim()
    with repository.db.session() as connection:
        connection.execute(
            "UPDATE recordings SET generation=1,deleted_at='deleted' WHERE id=?", (recording.id,)
        )
    assert not repository.commit_stage(
        StageResult(job_id=job.id, generation=0, stage="speech", artifact_path="late.json")
    )


def test_worker_restart_publishes_completed_speech_without_rerunning(jobs, settings, tmp_path):
    import json

    from meetinglog.jobs.runner import Worker
    from meetinglog.transcripts.repository import TranscriptRepository

    repository, recording = jobs
    job = repository.enqueue(recording.id, "process", None, "local_only")
    with Worker(settings, repository.db):
        repository.claim()
        artifact = tmp_path / "completed-speech.json"
        artifact.write_text(
            json.dumps(
                {
                    "turns": [],
                    "speakers": [],
                    "no_speech": True,
                    "provider": "test",
                    "model": "silence",
                }
            )
        )
        assert repository.commit_stage(
            StageResult(job_id=job.id, generation=0, stage="speech", artifact_path=str(artifact))
        )

    def forbidden_command(_):
        raise AssertionError("completed speech must not be inferred twice")

    with Worker(settings, repository.db, stage_command=forbidden_command) as worker:
        assert worker.run_once()
    completed = repository.get(job.id)
    assert completed.state == "succeeded"
    assert completed.stage == "no_speech"
    assert TranscriptRepository(repository.db).current(recording.id).turns == []


@pytest.mark.parametrize("failed", [False, True])
def test_stage_attempt_history_survives_success_or_failure(
    settings, db, input_service, tmp_path, failed
):
    import json
    import sys

    from meetinglog.jobs.repository import JobRepository
    from meetinglog.jobs.runner import Worker

    from tests.audio_fixtures import write_silence

    record = input_service.import_file(
        "audio.wav", [write_silence(tmp_path / "history.wav").read_bytes()]
    )
    job = JobRepository(db).enqueue(record.id, "process", None, "local_only")

    def command(request):
        script = """
import json,sys
from pathlib import Path
path=Path(sys.argv[1]);path.parent.mkdir(parents=True,exist_ok=True)
events=[{'event':'retry','location':'api','attempt':1,'reason':'upstream_network','duplicate_cost_possible':True,'secret':'never-store'}, {'event':'request_started','location':'api','attempt':2,'duplicate_cost_possible':True}, {'event':'speech_progress','phase':'asr','completed':2,'total':4,'secret':'never-store'}]
path.with_suffix('.events.jsonl').write_text(''.join(json.dumps(event)+'\\n' for event in events))
if sys.argv[2]=='True':sys.exit(1)
path.write_text(json.dumps({'turns':[],'speakers':[],'no_speech':True,'provider':'test','model':'fixed'}))
"""
        return [sys.executable, "-c", script, request.output_path, str(failed)]

    with Worker(settings, db, stage_command=command) as worker:
        worker.run_once()
    with db.session() as connection:
        events = [
            json.loads(row[0])
            for row in connection.execute(
                "SELECT metadata FROM job_events WHERE job_id=? AND event IN ('retry','request_started') ORDER BY id",
                (job.id,),
            )
        ]
    assert [event["attempt"] for event in events] == [1, 2]
    assert events[0]["duplicate_cost_possible"] is True
    assert "never-store" not in json.dumps(events)
    # Crash-recovery ingestion is idempotent and the exported history retains cost warnings.
    with Worker(settings, db):
        pass
    from meetinglog.exports import processing_history

    with db.session() as connection:
        history = processing_history(connection, record.id)
    assert len([entry for entry in history if entry["event"] == "retry"]) == 1
    assert any(entry["metadata"].get("duplicate_cost_possible") for entry in history)
    progress = next(entry for entry in history if entry["event"] == "speech_progress")
    assert progress["job_id"] == job.id
    assert progress["metadata"] == {"phase": "asr", "completed": 2, "total": 4}
