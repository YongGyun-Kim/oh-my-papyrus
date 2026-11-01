import argparse
from pathlib import Path

from meetinglog.app import create_app
from meetinglog.config import Settings


def main():
    parser = argparse.ArgumentParser(prog="meetinglog")
    parser.add_argument(
        "command", choices=["serve", "schema", "worker", "prepare-models", "doctor", "evaluate"]
    )
    parser.add_argument("--models", nargs="+", default=["vad", "asr", "aligner", "diarizer"])
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--mode", choices=["local_only", "auto", "api"], default="local_only")
    parser.add_argument("--engine", choices=["qwen", "whisper"], default="qwen")
    args = parser.parse_args()
    if args.command == "schema":
        import json

        print(json.dumps(create_app().openapi(), ensure_ascii=False))
    elif args.command == "prepare-models":
        from meetinglog.engines.models import ModelRegistry
        from meetinglog.jobs.locks import inference_lock

        settings = Settings()
        with inference_lock(settings, exclusive=True):
            ModelRegistry(settings).prepare(args.models)
    elif args.command == "evaluate":
        from meetinglog.evaluation import evaluate_manifest
        from meetinglog.recordings.storage import atomic_json

        if not args.manifest or not args.output:
            parser.error("evaluate에는 --manifest와 --output이 필요합니다")
        report = evaluate_manifest(args.manifest, args.mode, engine=args.engine)
        atomic_json(args.output, report.model_dump(mode="json"))
        print(f"{report.status}: {args.output}")
    elif args.command == "doctor":
        import json
        import shutil

        from meetinglog.db import Database
        from meetinglog.settings_api import readiness

        settings = Settings()
        db = Database(settings.database_path)
        db.migrate()

        print(
            json.dumps(
                {
                    "ffmpeg": bool(shutil.which("ffmpeg")),
                    "ffprobe": bool(shutil.which("ffprobe")),
                    **readiness(db, settings).model_dump(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "worker":
        import signal

        from meetinglog.db import Database
        from meetinglog.jobs.runner import Worker

        settings = Settings()
        db = Database(settings.database_path)
        db.migrate()
        with Worker(settings, db) as worker:
            signal.signal(signal.SIGTERM, lambda *_: worker.stop.set())
            signal.signal(signal.SIGINT, lambda *_: worker.stop.set())
            worker.run()
    else:
        import uvicorn

        uvicorn.run(create_app(Settings()), host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
