import { useEffect, useRef, useState } from "react";
import { FileAudio, Upload, X } from "lucide-react";
import { api, message } from "../../lib/api";
import type { InputLimits } from "../../lib/types";

export function UploadDialog({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: (id: string) => void;
}) {
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [limits, setLimits] = useState<InputLimits | null>(null);
  const busy = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    void api.inputLimits(controller.signal).then(
      (value) => {
        if (!controller.signal.aborted) setLimits(value);
      },
      (reason) => {
        if (!controller.signal.aborted) setError(message(reason));
      },
    );
    return () => controller.abort();
  }, []);
  const sizeLimit = limits
    ? `${limits.max_upload_bytes / 1_000_000_000}GB`
    : "";
  const upload = async (file?: File) => {
    if (!file || !limits || busy.current) return;
    setError("");
    if (file.size > limits.max_upload_bytes) {
      setError(`${sizeLimit} 이하의 파일을 선택해 주세요.`);
      return;
    }
    if (!file.size) {
      setError("파일이 비어 있어요. 다른 녹음 파일을 선택해 주세요.");
      return;
    }
    busy.current = true;
    setName(file.name);
    setProgress(0);
    try {
      const record = await api.upload(file, setProgress);
      onSaved(record.id);
    } catch (reason) {
      setError(message(reason));
      setProgress(null);
    } finally {
      busy.current = false;
    }
  };
  return (
    <div className="modal-backdrop">
      <section
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="upload-title"
      >
        <div className="modal-heading">
          <div>
            <span className="eyebrow">파일 입력</span>
            <h2 id="upload-title">녹음 파일 가져오기</h2>
          </div>
          <button
            className="icon-button"
            aria-label="닫기"
            disabled={progress !== null}
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </div>
        <label
          className={`dropzone ${progress !== null ? "busy" : ""}`}
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            void upload(event.dataTransfer.files[0]);
          }}
        >
          <span className="drop-icon">
            <FileAudio size={28} strokeWidth={1.6} />
          </span>
          <strong>
            {progress === null ? "파일을 선택하거나 여기에 놓으세요" : name}
          </strong>
          <span>
            {limits
              ? `MP3, M4A, WAV, WebM 등 · 최대 ${limits.max_duration_ms / 3_600_000}시간 / ${sizeLimit}`
              : error
                ? "업로드 한도를 확인하지 못했어요."
                : "업로드 한도를 확인하고 있어요."}
          </span>
          <input
            aria-label="녹음 파일"
            type="file"
            accept="audio/*,.mp4,.webm,.m4a,.wav,.mp3,.flac,.ogg,.aiff"
            disabled={progress !== null || !limits}
            onChange={(event) => {
              void upload(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
          {progress === null && limits && (
            <span className="button secondary">
              <Upload size={16} /> 파일 선택
            </span>
          )}
        </label>
        {progress !== null && (
          <div className="upload-progress">
            <progress max="1" value={progress} aria-label="파일 전송 진행" />
            <p>
              {progress === 1
                ? "파일을 확인하고 있어요."
                : `전송 중 ${Math.round(progress * 100)}%`}
            </p>
          </div>
        )}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <p className="help">
          원본 파일은 보관하고, 음성을 글로 바꾼 뒤 내용을 분석해요.
        </p>
      </section>
    </div>
  );
}
