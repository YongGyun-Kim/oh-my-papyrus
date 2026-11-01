import fcntl
import threading
from pathlib import Path

from meetinglog.analysis.settings import saved_analysis_settings
from meetinglog.config import Settings
from meetinglog.db import ApiError, Database, require_recording
from meetinglog.domain import Job, SpeechResult, StageRequest, new_id
from meetinglog.jobs.locks import inference_lock
from meetinglog.jobs.process import ProcessRunner, local_command
from meetinglog.jobs.repository import JobRepository
from meetinglog.recordings.storage import Storage, atomic_json
from meetinglog.transcripts.repository import TranscriptRepository


class Worker:
    def __init__(self, settings: Settings, db: Database, stage_command=None):
        self.settings, self.db = settings, db
        self.repository = JobRepository(db)
        self.stage_command = stage_command or local_command
        self.uses_default_executor = stage_command is None
        self.stop = threading.Event()
        self.lock = None

    def __enter__(self):
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.lock = (self.settings.data_dir / "worker.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            self.lock.close()
            self.lock = None
            raise ApiError("worker_running", "이미 실행 중인 처리 워커가 있습니다", 409) from error
        # A killed worker's guard reaps its engine before releasing this lock.
        with (self.settings.data_dir / "inference.lock").open("a") as ownership:
            fcntl.flock(ownership, fcntl.LOCK_EX)
            self.recover_events()
            self.repository.recover()
        return self

    def recover_events(self):
        from meetinglog.jobs.events import stage_events

        with self.db.session() as connection:
            rows = connection.execute("SELECT id,recording_id FROM jobs").fetchall()
        for row in rows:
            directory = (
                Storage(self.settings.data_dir).directory(row["recording_id"]) / "jobs" / row["id"]
            )
            for path in sorted(
                directory.rglob("*.events.jsonl"), key=lambda path: path.stat().st_mtime
            ):
                stage = "analysis" if path.name.startswith("analysis") else "speech"
                for key, name, metadata in stage_events(path):
                    self.repository.event(row["id"], stage, name, metadata, key)

    def __exit__(self, *args):
        self.stop.set()
        if self.lock:
            fcntl.flock(self.lock, fcntl.LOCK_UN)
            self.lock.close()
            self.lock = None

    def _speech(self, job: Job, artifact: str):
        speech = SpeechResult.model_validate_json(Path(artifact).read_text())
        with self.db.session(immediate=True) as connection:
            transcript = TranscriptRepository(self.db).save_generated(
                job.recording_id, speech, job.generation, job.id, connection=connection
            )
            connection.execute(
                "UPDATE jobs SET transcript_id=?,speech_artifact=?,stage='analysis' WHERE id=? AND state='running' AND cancel_requested=0",
                (transcript.id, artifact, job.id),
            )
            normalized = Path(artifact).with_suffix(".wav")
            if normalized.is_file():
                connection.execute(
                    "UPDATE recordings SET normalized_path=? WHERE id=? AND deleted_at IS NULL",
                    (str(normalized), job.recording_id),
                )
        return speech

    def _stage(self, job: Job, stage: str, input_path: str, duration_ms: int):
        attempt = self.repository.raw(job.id)["attempts"]
        directory = (
            Storage(self.settings.data_dir).directory(job.recording_id)
            / "jobs"
            / job.id
            / f"attempt-{attempt}"
        )
        request = StageRequest(
            job_id=job.id,
            recording_id=job.recording_id,
            generation=job.generation,
            stage=stage,
            input_path=input_path,
            output_path=str(directory / f"{stage}-{new_id()}.json"),
            mode=job.mode,
            form=job.form,
            analysis_settings=saved_analysis_settings(self.db) if stage == "analysis" else None,
        )
        env = {
            f"MEETINGLOG_{name.upper()}": str(value)
            for name, value in self.settings.model_dump().items()
            if value is not None
        }
        if self.settings.openai_api_key:
            env["OPENAI_API_KEY"] = self.settings.openai_api_key
        runner = ProcessRunner(
            self.stage_command,
            cancelled=lambda: self.stop.is_set() or self.repository.cancelled(job.id),
            heartbeat=lambda: self.repository.heartbeat(job.id),
            env=env,
            on_event=lambda key, name, metadata: self.repository.event(
                job.id, stage, name, metadata, key
            ),
        )
        seconds = duration_ms / 1000
        timeout = max(300, seconds * 0.25) if stage == "analysis" else max(180, seconds * 0.5)
        selected = request.analysis_settings
        ollama_settings = self.settings
        if selected and selected.provider == "ollama":
            ollama_settings = self.settings.model_copy(update={"ollama_model": selected.model})
        try:
            result = runner.run(request, timeout)
        except ApiError as error:
            if (
                error.code in ("stage_timeout", "job_cancelled")
                and stage == "analysis"
                and self.uses_default_executor
                and (selected is None or selected.provider == "ollama")
            ):
                from meetinglog.engines.local_analysis import unload_ollama

                unload_ollama(ollama_settings)
            if (
                error.code != "stage_timeout"
                or job.mode != "auto"
                or not self.settings.openai_api_key
                or selected is not None
            ):
                raise
            self.repository.event(
                job.id, stage, "fallback", {"reason": "stage_timeout", "location": "api"}
            )
            result = runner.run(
                request.model_copy(
                    update={
                        "mode": "api",
                        "output_path": str(directory / f"{stage}-{new_id()}.json"),
                    }
                ),
                timeout,
            )
            result.metadata["fallback_reason"] = "stage_timeout"
        if self.repository.cancelled(job.id):
            raise ApiError("job_cancelled", "작업이 취소되었습니다", 409)
        self.repository.event(job.id, stage, "engine_result", result.metadata)
        return result

    def run_once(self) -> bool:
        if self.lock is None:
            raise RuntimeError("Worker must hold its singleton lock")
        try:
            with inference_lock(self.settings, blocking=False):
                return self._run_once()
        except BlockingIOError:
            return False

    def _run_once(self) -> bool:
        from meetinglog.recordings.deletion import DeletionService

        DeletionService(self.settings, self.db).cleanup_pending()
        job = self.repository.claim()
        if job is None:
            return False
        try:
            with self.db.session() as connection:
                record = dict(require_recording(connection, job.recording_id))
            if job.kind == "process":
                raw = self.repository.raw(job.id)
                artifact = raw["speech_artifact"]
                if not artifact:
                    artifact = self._stage(
                        job, "speech", record["original_path"], record["duration_ms"]
                    ).artifact_path
                speech = self._speech(job, artifact)
                if speech.no_speech:
                    self.repository.finish(job.id, "succeeded", stage="no_speech")
                    return True
                self.repository.finish(job.id, "succeeded", stage="transcribed")
                return True
            current_job = self.repository.raw(job.id)
            transcript = TranscriptRepository(self.db).get(current_job["transcript_id"])
            if not transcript.turns:
                self.repository.finish(job.id, "succeeded", stage="no_speech")
                return True
            directory = (
                Storage(self.settings.data_dir).directory(job.recording_id) / "jobs" / job.id
            )
            transcript_path = directory / "transcript.json"
            atomic_json(transcript_path, transcript.model_dump(mode="json"))
            artifact = current_job["analysis_artifact"]
            if not artifact:
                artifact = self._stage(
                    job, "analysis", str(transcript_path), record["duration_ms"]
                ).artifact_path
            from meetinglog.analysis.service import AnalysisService

            AnalysisService(self.db).publish(job, Path(artifact))
            self.repository.finish(job.id, "succeeded", stage="complete")
        except ApiError as error:
            self.repository.finish(job.id, "interrupted" if self.stop.is_set() else "failed", error)
        except Exception:
            self.repository.finish(
                job.id,
                "failed",
                ApiError(
                    "processing_failed",
                    "처리에 실패했습니다. 준비 상태를 확인한 뒤 다시 시도하세요",
                    503,
                ),
            )
        return True

    def run(self):
        while not self.stop.is_set():
            if not self.run_once():
                self.stop.wait(0.5)
