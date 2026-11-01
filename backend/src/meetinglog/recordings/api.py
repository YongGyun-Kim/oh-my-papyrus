import re
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import Field

from meetinglog.analysis.forms import FORMS, FormOption
from meetinglog.analysis.repository import AnalysisRepository
from meetinglog.db import ApiError, require_recording
from meetinglog.domain import (
    AnalysisForm,
    AnalysisVersion,
    Contract,
    Job,
    Mode,
    Recording,
    Transcript,
)
from meetinglog.exports import Exporter, processing_history
from meetinglog.jobs.repository import JobRepository, as_job
from meetinglog.recordings.deletion import DeletionService
from meetinglog.recordings.media import prepare_playback, probe
from meetinglog.recordings.service import InputService, as_recording
from meetinglog.recordings.storage import Storage
from meetinglog.settings_api import effective_mode
from meetinglog.transcripts.repository import TranscriptRepository

router = APIRouter(prefix="/api/recordings", tags=["recordings"])


class DraftInput(Contract):
    title: str = Field(default="새 녹음", max_length=200)
    source: Literal["microphone"] = "microphone"


class FinalizeInput(Contract):
    last_sequence: int = Field(ge=0)


class RecordingSummary(Recording):
    job_state: str | None = None
    job_stage: str | None = None


class RecordingList(Contract):
    items: list[RecordingSummary]


class ProcessingEvent(Contract):
    job_id: str
    kind: str
    mode: Mode
    state: str
    stage: str
    event: str
    created_at: str
    metadata: dict[str, str | int | float | bool | None]


class RecordingDetail(Contract):
    recording: Recording
    transcript: Transcript | None
    analysis: AnalysisVersion | None
    analysis_stale: bool
    job: Job | None
    processing_history: list[ProcessingEvent]


class ProcessingInput(Contract):
    mode: Mode


class AnalyzeInput(ProcessingInput):
    transcript_id: str
    form: AnalysisForm


class InputLimits(Contract):
    max_upload_bytes: int
    max_duration_ms: int


def service(request: Request) -> InputService:
    return InputService(request.app.state.settings, request.app.state.db)


@router.get("/limits", response_model=InputLimits)
def input_limits(request: Request):
    settings = request.app.state.settings
    return InputLimits(
        max_upload_bytes=settings.max_upload_bytes,
        max_duration_ms=settings.max_duration_ms,
    )


@router.get("/analysis-forms", response_model=list[FormOption])
def analysis_forms():
    return FORMS


@router.post("", response_model=Recording, status_code=201)
def upload(request: Request, file: UploadFile):
    recording = service(request).import_file(
        file.filename or "녹음", iter(lambda: file.file.read(1024 * 1024), b"")
    )
    JobRepository(request.app.state.db).ensure_initial(
        recording.id, effective_mode(request.app.state.db, request.app.state.settings)
    )
    return recording


@router.post("/drafts", response_model=Recording, status_code=201)
def draft(request: Request, body: DraftInput):
    return service(request).create(body.source, body.title)


@router.put("/{recording_id}/chunks/{sequence}")
async def chunk(request: Request, recording_id: str, sequence: int):
    buffer = bytearray()
    async for body in request.stream():
        buffer.extend(body)
        if len(buffer) > 32 * 1024 * 1024:
            raise ApiError(
                "chunk_too_large",
                "녹음 전송이 지연되었습니다. 녹음을 종료한 뒤 파일로 가져오세요",
                413,
            )
    return {"digest": service(request).append_chunk(recording_id, sequence, bytes(buffer))}


@router.post("/{recording_id}/finalize", response_model=Recording)
def finalize(request: Request, recording_id: str, body: FinalizeInput):
    recording = service(request).finalize(recording_id, body.last_sequence)
    JobRepository(request.app.state.db).ensure_initial(
        recording.id, effective_mode(request.app.state.db, request.app.state.settings)
    )
    return recording


@router.get("", response_model=RecordingList)
def list_recordings(request: Request):
    with request.app.state.db.session() as connection:
        rows = connection.execute(
            "SELECT r.*,(SELECT state FROM jobs WHERE recording_id=r.id ORDER BY created_at DESC LIMIT 1) AS job_state,(SELECT stage FROM jobs WHERE recording_id=r.id ORDER BY created_at DESC LIMIT 1) AS job_stage FROM recordings r WHERE r.deleted_at IS NULL ORDER BY r.created_at DESC"
        ).fetchall()
        return RecordingList(
            items=[
                RecordingSummary.model_validate(
                    {key: row[key] for key in RecordingSummary.model_fields if key in row.keys()}
                )
                for row in rows
            ]
        )


@router.get("/{recording_id}", response_model=RecordingDetail)
def detail(request: Request, recording_id: str):
    db = request.app.state.db
    with db.session() as connection:
        recording = as_recording(require_recording(connection, recording_id))
        row = connection.execute(
            "SELECT * FROM jobs WHERE recording_id=? ORDER BY created_at DESC LIMIT 1",
            (recording_id,),
        ).fetchone()
        job = as_job(row) if row else None
        history = processing_history(connection, recording_id)
    transcript = TranscriptRepository(db).current(recording_id)
    analysis = AnalysisRepository(db).current(recording_id)
    return RecordingDetail(
        recording=recording,
        transcript=transcript,
        analysis=analysis,
        analysis_stale=bool(
            analysis and (transcript is None or analysis.transcript_id != transcript.id)
        ),
        job=job,
        processing_history=history,
    )


def audio_type(path: Path) -> str | None:
    with path.open("rb") as source:
        header = source.read(16)
    if header[:4] == b"RIFF" and header[8:12] == b"WAVE":
        return "audio/wav"
    if header[4:8] == b"ftyp":
        return "audio/mp4"
    if header[:4] == b"\x1aE\xdf\xa3":
        return "audio/webm"
    if header[:3] == b"ID3" or (len(header) > 1 and header[0] == 255 and header[1] & 224 == 224):
        return "audio/mpeg"
    if header[:4] == b"fLaC":
        return "audio/flac"
    return None


@router.get("/{recording_id}/audio")
def audio(request: Request, recording_id: str):
    with request.app.state.db.session() as connection:
        row = require_recording(connection, recording_id)
        path = Path(row["original_path"]) if row["original_path"] else None
        normalized = row["normalized_path"]
    if path is None or not path.is_file():
        raise ApiError("audio_unavailable", "재생할 음성이 없습니다", 404)
    content_type = audio_type(path)
    needs_wav = content_type == "audio/mp4" and probe(path).codec not in ("aac", "mp3")
    if content_type == "audio/webm" or needs_wav:
        # WebM 길이 정보와 브라우저 미지원 코덱은 원본을 보존한 재생용 파일로 처리한다.
        with Storage(request.app.state.settings.data_dir).input_lock(recording_id):
            with request.app.state.db.session() as connection:
                require_recording(connection, recording_id)
            playback = path.with_name("playback.wav" if needs_wav else "playback.webm")
            if not playback.is_file():
                prepare_playback(path, playback)
            path = playback
            if needs_wav:
                content_type = "audio/wav"
    if content_type is None:
        if not normalized or not Path(normalized).is_file():
            raise ApiError("audio_not_ready", "재생용 음성을 준비하고 있습니다", 503)
        path, content_type = Path(normalized), "audio/wav"
    requested = request.headers.get("range")
    if requested:
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
        if (
            match is None
            or (not match[1] and not match[2])
            or (match[1] and int(match[1]) >= path.stat().st_size)
            or (match[1] and match[2] and int(match[2]) < int(match[1]))
        ):
            raise ApiError("invalid_range", "재생 범위가 올바르지 않습니다", 416)
    return FileResponse(
        path, media_type=content_type, headers={"X-Content-Type-Options": "nosniff"}
    )


@router.post("/{recording_id}/process", response_model=Job)
def process(request: Request, recording_id: str, body: ProcessingInput):
    return JobRepository(request.app.state.db).enqueue(recording_id, "process", None, body.mode)


@router.post("/{recording_id}/analyze", response_model=Job)
def analyze(request: Request, recording_id: str, body: AnalyzeInput):
    return JobRepository(request.app.state.db).enqueue(
        recording_id, "analyze", body.transcript_id, body.mode, form=body.form
    )


@router.delete("/{recording_id}", status_code=202)
def delete(request: Request, recording_id: str):
    DeletionService(request.app.state.settings, request.app.state.db).request(recording_id)
    return {"status": "deleting"}


@router.get("/{recording_id}/export")
def export(
    request: Request,
    recording_id: str,
    format: Literal["json", "markdown", "analysis_markdown"] = "json",
    transcript_id: str | None = None,
    analysis_id: str | None = None,
):
    exporter = Exporter(request.app.state.db)
    payload = exporter.payload(recording_id, transcript_id, analysis_id)
    extension = "json" if format == "json" else "md"
    suffix = "-analysis" if format == "analysis_markdown" else ""
    headers = {
        "Content-Disposition": f'attachment; filename="recording-{recording_id}{suffix}.{extension}"'
    }
    return (
        JSONResponse(payload, headers=headers)
        if format == "json"
        else PlainTextResponse(
            exporter.markdown(payload, analysis_only=format == "analysis_markdown"),
            media_type="text/markdown",
            headers=headers,
        )
    )
