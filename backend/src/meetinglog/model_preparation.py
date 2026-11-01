from tempfile import TemporaryDirectory
from threading import Event, Lock, Thread
from typing import Literal

from pydantic import Field

from meetinglog.config import Settings
from meetinglog.db import ApiError
from meetinglog.domain import Contract, SpeechModel, StageRequest, new_id
from meetinglog.engines.models import ModelRegistry
from meetinglog.jobs.process import ProcessRunner, local_command


class ModelDownload(Contract):
    model: SpeechModel | None = None
    state: Literal["idle", "queued", "downloading", "verifying", "succeeded", "failed"] = "idle"
    completed: int = Field(default=0, ge=0)
    total: int | None = Field(default=None, gt=0)
    error_message: str | None = None


class ModelPreparation:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.command = local_command
        self._lock = Lock()
        self._stopping = Event()
        self._thread: Thread | None = None
        self._status = ModelDownload()

    def status(self) -> ModelDownload:
        with self._lock:
            return self._status.model_copy()

    def start(self, model: SpeechModel) -> ModelDownload:
        with self._lock:
            if self._stopping.is_set():
                raise ApiError("server_stopping", "서버가 종료 중이에요.", 503)
            if self._thread and self._thread.is_alive():
                if self._status.model == model:
                    return self._status.model_copy()
                raise ApiError(
                    "model_download_active",
                    "다른 모델을 받고 있어요. 끝난 뒤 다시 시도해 주세요.",
                    409,
                )
            self._status = ModelDownload(model=model, state="queued")
            self._thread = Thread(target=self._run, args=(model,), daemon=True)
            self._thread.start()
            return self._status.model_copy()

    def _run(self, model: SpeechModel):
        try:
            self.settings.data_dir.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(
                prefix="model-download-", dir=self.settings.data_dir
            ) as directory:
                request = StageRequest(
                    job_id=new_id(),
                    recording_id="",
                    generation=0,
                    stage="models",
                    input_path="",
                    output_path=f"{directory}/result.json",
                    mode="local_only",
                    model_name=model,
                )

                def progress(key, event, metadata):
                    if event != "model_progress":
                        return
                    with self._lock:
                        self._status = ModelDownload(
                            model=model,
                            state=metadata.get("phase", "downloading"),
                            completed=metadata.get("completed", 0),
                            total=metadata.get("total"),
                        )

                fields = (
                    "data_dir",
                    "models_dir",
                    "asr_repo",
                    "aligner_repo",
                    "vad_repo",
                    "diarizer_repo",
                )
                runner = ProcessRunner(
                    self.command,
                    cancelled=self._stopping.is_set,
                    on_event=progress,
                    env={
                        f"MEETINGLOG_{name.upper()}": str(getattr(self.settings, name))
                        for name in fields
                    },
                )
                runner.run(request, timeout_s=None)
                ModelRegistry(self.settings).require(model)
            with self._lock:
                self._status = self._status.model_copy(update={"state": "succeeded"})
        except Exception as error:
            message = (
                "모델을 받지 못했어요. 인터넷 연결과 저장 공간을 확인한 뒤 다시 시도해 주세요."
            )
            if isinstance(error, ApiError) and error.code in (
                "model_dependencies_missing",
                "model_storage_permission",
                "model_storage_full",
                "model_validation_failed",
            ):
                message = error.message
            elif self._stopping.is_set():
                message = "서버가 종료되어 다운로드를 중단했어요. 다시 시도해 주세요."
            with self._lock:
                self._status = self._status.model_copy(
                    update={"state": "failed", "error_message": message}
                )

    def close(self):
        self._stopping.set()
        if self._thread:
            self._thread.join(timeout=5)
