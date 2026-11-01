import hashlib
import os
import shutil
from collections.abc import Iterable
from pathlib import Path

from meetinglog.config import Settings
from meetinglog.db import ApiError, Database, require_recording
from meetinglog.domain import Recording, new_id
from meetinglog.recordings.media import probe
from meetinglog.recordings.storage import Storage, atomic_write


class InputConflict(ApiError):
    def __init__(self, code="chunk_conflict", message="녹음 데이터의 순서와 내용을 확인하세요"):
        super().__init__(code, message, 409)


def as_recording(row) -> Recording:
    return Recording.model_validate({name: row[name] for name in Recording.model_fields})


class InputService:
    def __init__(self, settings: Settings, db: Database):
        self.settings, self.db = settings, db
        self.storage = Storage(settings.data_dir)

    def create(self, source: str, title: str) -> Recording:
        record = Recording(
            id=new_id(),
            title=title.strip()[:200] or "새 녹음",
            source=source,
            input_state="recording" if source == "microphone" else "uploading",
        )
        with self.db.session(immediate=True) as connection:
            connection.execute(
                "INSERT INTO recordings(id,title,source,input_state,created_at,generation) VALUES (?,?,?,?,?,?)",
                (
                    record.id,
                    record.title,
                    record.source,
                    record.input_state,
                    record.created_at.isoformat(),
                    0,
                ),
            )
        return record

    def append_chunk(self, recording_id: str, sequence: int, body: bytes) -> str:
        if sequence < 0 or sequence > 100_000 or not body:
            raise ApiError("invalid_chunk", "녹음 데이터가 비어 있거나 순서가 잘못되었습니다")
        digest = hashlib.sha256(body).hexdigest()
        with self.storage.input_lock(recording_id):
            with self.db.session(immediate=True) as connection:
                record = require_recording(connection, recording_id)
                previous = connection.execute(
                    "SELECT * FROM chunks WHERE recording_id=? AND sequence=?",
                    (recording_id, sequence),
                ).fetchone()
                if previous:
                    if previous["digest"] != digest:
                        raise InputConflict()
                    return digest
                if record["input_state"] not in ("recording", "uploading"):
                    raise InputConflict("input_closed", "이미 종료된 녹음입니다")
                if record["byte_count"] + len(body) > self.settings.max_upload_bytes:
                    raise ApiError(
                        "input_too_large",
                        "업로드 용량 제한을 넘었어요. 더 작은 파일을 선택해 주세요.",
                        413,
                    )
                path = self.storage.directory(recording_id) / "chunks" / f"{sequence:06d}.bin"
                atomic_write(path, body)
                connection.execute(
                    "INSERT INTO chunks VALUES (?,?,?,?)",
                    (recording_id, sequence, digest, len(body)),
                )
                connection.execute(
                    "UPDATE recordings SET byte_count=byte_count+? WHERE id=?",
                    (len(body), recording_id),
                )
            return digest

    def finalize(self, recording_id: str, last_sequence: int) -> Recording:
        # Freeze only this input; long assembly/decoding must not hold SQLite's write lock.
        with self.storage.input_lock(recording_id):
            try:
                with self.db.session() as connection:
                    record = require_recording(connection, recording_id)
                    if record["input_state"] == "ready":
                        return as_recording(record)
                    generation = record["generation"]
                    rows = connection.execute(
                        "SELECT sequence FROM chunks WHERE recording_id=? ORDER BY sequence",
                        (recording_id,),
                    ).fetchall()
                    if last_sequence < 0 or [row[0] for row in rows] != list(
                        range(last_sequence + 1)
                    ):
                        raise InputConflict(
                            "missing_chunk", "녹음 데이터 일부가 아직 저장되지 않았습니다"
                        )
                directory = self.storage.directory(recording_id)
                original = directory / "original"
                temporary = directory / "original.part"
                with temporary.open("wb") as output:
                    for row in rows:
                        with (directory / "chunks" / f"{row[0]:06d}.bin").open("rb") as source:
                            shutil.copyfileobj(source, output, 1024 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
                temporary.replace(original)
                info = probe(original)
                if info.duration_ms > self.settings.max_duration_ms:
                    raise ApiError("input_too_long", "최대 2시간의 녹음만 처리할 수 있습니다")
                with self.db.session(immediate=True) as connection:
                    current = require_recording(connection, recording_id)
                    if current["generation"] != generation:
                        raise InputConflict("stale_generation", "녹음 상태가 변경되었습니다")
                    connection.execute(
                        "UPDATE recordings SET input_state='ready',duration_ms=?,original_path=?,error_code=NULL WHERE id=?",
                        (info.duration_ms, str(original), recording_id),
                    )
                    return as_recording(require_recording(connection, recording_id))
            except ApiError as error:
                if error.status != 409:
                    with self.db.session(immediate=True) as connection:
                        connection.execute(
                            "UPDATE recordings SET input_state='invalid',error_code=? WHERE id=? AND deleted_at IS NULL",
                            (error.code, recording_id),
                        )
                raise

    def import_file(self, filename: str, chunks: Iterable[bytes]) -> Recording:
        safe_name = Path(filename.replace("\\", "/")).name[:200]
        record = self.create("file", Path(safe_name).stem or "가져온 녹음")
        with self.db.session() as connection:
            connection.execute(
                "UPDATE recordings SET filename=? WHERE id=?", (safe_name, record.id)
            )
        sequence = -1
        try:
            for body in chunks:
                if body:
                    sequence += 1
                    self.append_chunk(record.id, sequence, body)
            return self.finalize(record.id, sequence)
        except (ApiError, OSError):
            with self.db.session() as connection:
                connection.execute(
                    "UPDATE recordings SET input_state='invalid' WHERE id=?", (record.id,)
                )
            raise
