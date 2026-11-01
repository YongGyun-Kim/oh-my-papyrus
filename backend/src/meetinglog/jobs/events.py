import json
import os
from pathlib import Path

from meetinglog.domain import now

ALLOWED = {
    "provider",
    "model",
    "location",
    "quality",
    "fallback_reason",
    "reason",
    "attempt",
    "duplicate_cost_possible",
    "completed",
    "total",
    "phase",
}
EVENTS = {
    "request_started",
    "retry",
    "engine_result",
    "fallback",
    "local_started",
    "engine_failed",
    "analysis_progress",
    "speech_progress",
    "model_progress",
}


def append_event(path: Path, event: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"created_at": now().isoformat(), **event}, ensure_ascii=False) + "\n"
    with path.open("a") as output:
        output.write(line)
        output.flush()
        os.fsync(output.fileno())


def stage_events(path: Path):
    try:
        lines = path.read_text().splitlines(keepends=True)
    except FileNotFoundError:
        return
    for index, line in enumerate(lines):
        if not line.endswith("\n"):
            continue
        try:
            event = json.loads(line)
            if event.get("event") not in EVENTS:
                continue
            metadata = {
                key: value
                for key, value in event.items()
                if key in ALLOWED and (value is None or isinstance(value, (str, int, float, bool)))
            }
            yield f"{path.name}:{index}", event["event"], metadata
        except (ValueError, AttributeError):
            continue
