import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from meetinglog.db import ApiError
from meetinglog.domain import StageRequest, StageResult
from meetinglog.recordings.storage import atomic_json


def local_command(request: StageRequest) -> list[str]:
    path = Path(request.output_path).with_suffix(".request.json")
    atomic_json(path, request.model_dump())
    return [sys.executable, "-m", "meetinglog.engines.local_executor", str(path)]


def terminate(child: subprocess.Popen):
    if child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGTERM)
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
        except ProcessLookupError:
            child.wait()


class ProcessRunner:
    def __init__(
        self,
        command: Callable,
        cancelled: Callable[[], bool] = lambda: False,
        heartbeat: Callable = lambda: None,
        env: dict | None = None,
        on_event: Callable | None = None,
    ):
        self.command, self.cancelled, self.heartbeat = command, cancelled, heartbeat
        self.env = env or {}
        self.on_event = on_event or (lambda *args: None)

    def run(self, request: StageRequest, timeout_s: float | None) -> StageResult:
        output = Path(request.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.unlink(missing_ok=True)
        error_file = output.with_suffix(".error.json")
        error_file.unlink(missing_ok=True)
        events_file = output.with_suffix(".events.jsonl")
        events_file.unlink(missing_ok=True)
        from meetinglog.jobs.events import stage_events

        seen = set()
        progressed = time.monotonic()

        def consume_events():
            nonlocal progressed
            for key, name, metadata in stage_events(events_file):
                if key not in seen:
                    self.on_event(key, name, metadata)
                    seen.add(key)
                    if request.stage == "analysis" and name == "analysis_progress":
                        progressed = time.monotonic()

        environment = {
            **os.environ,
            **self.env,
            "HF_HUB_OFFLINE": "0" if request.stage == "models" else "1",
            "TRANSFORMERS_OFFLINE": "0" if request.stage == "models" else "1",
            "TOKENIZERS_PARALLELISM": "false",
        }
        last_heartbeat = 0.0
        control, lifetime = os.pipe()
        ownership_lock = Path(self.env.get("MEETINGLOG_DATA_DIR", output.parent)) / "inference.lock"
        with output.with_suffix(".log").open("ab") as log:
            try:
                child = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "meetinglog.jobs.stage_guard",
                        str(control),
                        str(ownership_lock),
                        str(output.with_suffix(".workspace")),
                        *(["--exclusive"] if request.stage == "models" else []),
                        *self.command(request),
                    ],
                    start_new_session=True,
                    stdout=log,
                    stderr=log,
                    env=environment,
                    pass_fds=(control,),
                )
            except BaseException:
                os.close(lifetime)
                raise
            finally:
                os.close(control)
            try:
                while child.poll() is None:
                    consume_events()
                    if self.cancelled():
                        raise ApiError("job_cancelled", "작업이 취소되었습니다", 409)
                    if timeout_s is not None and time.monotonic() - progressed > timeout_s:
                        raise ApiError(
                            "stage_timeout",
                            "처리 시간을 초과했습니다. 다시 시도하거나 처리 방식을 변경하세요",
                            503,
                            True,
                        )
                    if time.monotonic() - last_heartbeat > 1:
                        self.heartbeat()
                        last_heartbeat = time.monotonic()
                    time.sleep(0.05)
                if self.cancelled():
                    raise ApiError("job_cancelled", "작업이 취소되었습니다", 409)
                if child.returncode != 0:
                    if error_file.exists():
                        error = json.loads(error_file.read_text())
                        raise ApiError(
                            error["code"], error["message"], 503, error.get("retryable", False)
                        )
                    raise ApiError(
                        "engine_failed",
                        "음성 처리 엔진을 실행하지 못했습니다. 준비 상태를 확인하세요",
                        503,
                    )
                if not output.is_file():
                    raise ApiError("invalid_output", "처리 결과 파일이 생성되지 않았습니다", 503)
                data = json.loads(output.read_text())
                metadata = {
                    key: data[key]
                    for key in ("provider", "model")
                    if isinstance(data.get(key), str)
                }
                events_file = output.with_suffix(".events.json")
                if events_file.exists():
                    events = json.loads(events_file.read_text()).get("events", [])
                    if events:
                        metadata.update(
                            {
                                key: value
                                for key, value in events[-1].items()
                                if key in ("location", "quality", "fallback_reason")
                            }
                        )
                return StageResult(
                    job_id=request.job_id,
                    generation=request.generation,
                    stage=request.stage,
                    artifact_path=str(output),
                    metadata=metadata,
                )
            finally:
                os.close(lifetime)
                terminate(child)
                consume_events()
