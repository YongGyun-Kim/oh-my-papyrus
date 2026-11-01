import errno
import os
import sys
from pathlib import Path

from meetinglog.config import Settings
from meetinglog.db import ApiError
from meetinglog.domain import StageRequest
from meetinglog.engines.policy import EnginePolicy
from meetinglog.recordings.media import normalize
from meetinglog.recordings.storage import atomic_json


def execute(request: StageRequest, settings: Settings):
    if request.stage == "models":
        from meetinglog.engines.models import ModelRegistry
        from meetinglog.jobs.events import append_event

        if request.model_name is None:
            raise ApiError("unknown_model", "다운로드할 음성 모델을 선택해 주세요.", 422)
        events = Path(request.output_path).with_suffix(".events.jsonl")

        def report(completed=0, total=None, phase="downloading"):
            append_event(
                events,
                {"event": "model_progress", "phase": phase, "completed": completed, "total": total},
            )

        report()
        try:
            ModelRegistry(settings).prepare(
                [request.model_name], progress=report, force_download=True
            )
        except ImportError:
            raise ApiError(
                "model_dependencies_missing",
                "모델 설치에 필요한 패키지가 없어요. 서버에서 bash scripts/setup.sh를 실행해 주세요.",
                503,
            ) from None
        except Exception as error:
            code = "model_download_failed"
            message = (
                "모델을 받지 못했어요. 인터넷 연결과 저장 공간을 확인한 뒤 다시 시도해 주세요."
            )
            if isinstance(error, PermissionError):
                code = "model_storage_permission"
                message = (
                    "모델 폴더에 파일을 쓸 수 없어요. 서버 컴퓨터의 폴더 권한을 확인해 주세요."
                )
            elif isinstance(error, OSError) and error.errno == errno.ENOSPC:
                code = "model_storage_full"
                message = "저장 공간이 부족해요. 서버 컴퓨터의 공간을 확보한 뒤 다시 시도해 주세요."
            elif isinstance(error, ApiError) and error.code == "model_not_ready":
                code = "model_validation_failed"
                message = "다운로드한 모델 파일을 확인하지 못했어요. 다시 다운로드해 주세요."
            raise ApiError(code, message, 503) from None
        report(phase="verifying")
        return {"model": request.model_name}
    if request.stage == "speech":
        from meetinglog.engines.cloud_speech import CloudSpeech
        from meetinglog.engines.local_speech import prepared_speech

        policy = EnginePolicy(
            settings, event_path=Path(request.output_path).with_suffix(".events.jsonl")
        )

        def progress(phase, completed=0, total=None):
            policy.record(
                {
                    "stage": "speech",
                    "event": "speech_progress",
                    "phase": phase,
                    "completed": completed,
                    "total": total,
                }
            )

        normalized = Path(request.output_path).with_suffix(".wav")
        progress("normalize")
        normalize(Path(request.input_path), normalized)
        speech = policy.execute(
            "speech",
            request.mode,
            0,
            lambda: prepared_speech(settings).transcribe(normalized, progress=progress),
            lambda: CloudSpeech(settings).transcribe(normalized),
        )
        atomic_json(
            Path(request.output_path).with_suffix(".events.json"), {"events": policy.events}
        )
        return speech.model_dump(mode="json")
    if request.stage == "analysis":
        from meetinglog.analysis.service import AnalysisService
        from meetinglog.db import Database
        from meetinglog.domain import Transcript

        transcript = Transcript.model_validate_json(Path(request.input_path).read_text())
        service = AnalysisService(
            Database(settings.database_path),
            settings,
            event_path=Path(request.output_path).with_suffix(".events.jsonl"),
            workspace=Path(request.output_path).with_suffix(".workspace"),
        )
        version = service.generate_from(
            transcript,
            request.mode,
            request.form,
            analysis_settings=request.analysis_settings,
            settings_fixed=True,
        )
        atomic_json(
            Path(request.output_path).with_suffix(".events.json"), {"events": service.events}
        )
        return version.model_dump(mode="json")
    raise ApiError("unsupported_stage", "지원하지 않는 처리 단계입니다", 503)


def main():
    request = StageRequest.model_validate_json(Path(sys.argv[1]).read_text())
    os.environ["HF_HUB_OFFLINE"] = "0" if request.stage == "models" else "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "0" if request.stage == "models" else "1"
    try:
        atomic_json(Path(request.output_path), execute(request, Settings()))
    except ApiError as error:
        atomic_json(
            Path(request.output_path).with_suffix(".error.json"),
            {"code": error.code, "message": error.message, "retryable": error.retryable},
        )
        raise SystemExit(1) from None
    except Exception as error:
        print(f"Engine error: {type(error).__name__}", file=sys.stderr)
        atomic_json(
            Path(request.output_path).with_suffix(".error.json"),
            {
                "code": "engine_failed",
                "message": "처리 엔진 실행에 실패했습니다. 모델과 실행 환경을 확인하세요",
                "retryable": False,
            },
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
