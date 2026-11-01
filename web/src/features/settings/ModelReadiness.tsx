import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, Circle } from "lucide-react";
import { api, message } from "../../lib/api";
import type { ModelDownload, Readiness, SpeechModel } from "../../lib/types";

const names: Record<string, string> = {
  vad: "음성 구간 탐지",
  asr: "한국어 전사",
  aligner: "발언 시간 정렬",
  diarizer: "화자 구분",
  analysis: "대화 분석",
};
const activeStates = ["queued", "downloading", "verifying"];
const labels = {
  queued: "전사·분석이 끝나면 다운로드를 시작해요.",
  downloading: "모델을 받고 있어요.",
  verifying: "모델 파일을 확인하고 있어요.",
};

export function ModelReadiness({
  settings,
  refreshCount,
  onChanged,
}: {
  settings: Readiness;
  refreshCount: number;
  onChanged: () => void;
}) {
  const [download, setDownload] = useState<ModelDownload | null>(null);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState<SpeechModel | null>(null);
  const last = useRef<ModelDownload | null>(null);
  const revision = useRef(0);
  const mounted = useRef(true);
  const accept = useCallback(
    (next: ModelDownload) => {
      const previous = last.current;
      last.current = next;
      setDownload(next);
      if (
        (next.state === "succeeded" || next.state === "failed") &&
        (next.state !== previous?.state || next.model !== previous.model)
      )
        onChanged();
    },
    [onChanged],
  );
  const load = useCallback(
    async (signal?: AbortSignal) => {
      const current = ++revision.current;
      try {
        const result = await api.modelDownload(signal);
        if (
          !signal?.aborted &&
          mounted.current &&
          current === revision.current
        ) {
          accept(result);
          setError("");
        }
      } catch (reason) {
        if (!signal?.aborted && mounted.current && current === revision.current)
          setError(message(reason));
      }
    },
    [accept],
  );
  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    void load(controller.signal);
    return () => {
      mounted.current = false;
      controller.abort();
    };
  }, [load, refreshCount]);
  const pending = activeStates.includes(download?.state ?? "");
  useEffect(() => {
    if (!pending) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      await load(controller.signal);
      if (!controller.signal.aborted)
        timer = setTimeout(() => void poll(), 1000);
    };
    timer = setTimeout(() => void poll(), 1000);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [pending, load]);
  const start = async (name: SpeechModel) => {
    ++revision.current;
    setSubmitting(name);
    setError("");
    try {
      const result = await api.prepareModel(name);
      if (mounted.current) {
        ++revision.current;
        accept(result);
      }
    } catch (reason) {
      if (mounted.current) setError(message(reason));
    } finally {
      if (mounted.current) setSubmitting(null);
    }
  };
  return (
    <section className="settings-section">
      <h2>모델 준비 상태</h2>
      <p className="muted settings-description">
        음성 모델은 서버 컴퓨터에 다운로드해요. 페이지를 닫아도 서버가 실행
        중이면 계속 받아요. 파일 수를 기준으로 진행률을 표시해요.
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="engine-list">
        {settings.engines.map((engine) => {
          const name = names[engine.name] ?? engine.name;
          const analysis = engine.name === "analysis";
          const task = download?.model === engine.name ? download : null;
          const working = !!task && activeStates.includes(task.state);
          const measured =
            task?.state === "downloading" &&
            !!task.total &&
            task.completed <= task.total;
          const failed = task?.state === "failed";
          return (
            <div
              className="engine-row model-row"
              role="group"
              aria-label={name}
              key={engine.name}
            >
              {engine.ready && !working && !failed ? (
                <CheckCircle2 size={17} />
              ) : (
                <Circle size={17} />
              )}
              <div>
                <strong>{name}</strong>
                <small>
                  <a
                    href={
                      analysis
                        ? `https://ollama.com/library/${engine.repo_id.split(":")[0]}`
                        : `https://huggingface.co/${engine.repo_id}`
                    }
                    target="_blank"
                    rel="noreferrer"
                  >
                    {engine.repo_id}
                  </a>
                </small>
                {working && (
                  <div className="model-download-state" role="status">
                    <small>{labels[task.state as keyof typeof labels]}</small>
                    <div className="processing-progress">
                      <progress
                        aria-label={`${name} 모델 다운로드 진행률`}
                        max={measured ? task.total! : 1}
                        value={measured ? task.completed : undefined}
                      />
                      {measured && (
                        <small>
                          {Math.round((task.completed / task.total!) * 100)}% ·{" "}
                          {task.completed}/{task.total} 파일
                        </small>
                      )}
                    </div>
                  </div>
                )}
                {failed && (
                  <p className="error" role="alert">
                    {task.error_message}
                  </p>
                )}
                {!engine.ready && !working && (
                  <div className="model-guide">
                    {analysis && (
                      <small>
                        Ollama를 실행한 뒤 모델을 다운로드해 주세요.{" "}
                        <a
                          href="https://ollama.com/download"
                          target="_blank"
                          rel="noreferrer"
                        >
                          Ollama 설치
                        </a>
                      </small>
                    )}
                    <code>
                      {analysis
                        ? `ollama pull ${engine.repo_id}`
                        : `uv run --extra speech meetinglog prepare-models --models ${engine.name}`}
                    </code>
                  </div>
                )}
              </div>
              <span className="status">
                {working
                  ? "준비 중"
                  : failed
                    ? "다운로드 실패"
                    : engine.ready
                      ? "준비됨"
                      : "준비 필요"}
              </span>
              {!analysis && (
                <button
                  className="button secondary"
                  disabled={submitting !== null || pending || !download}
                  onClick={() => void start(engine.name as SpeechModel)}
                >
                  {submitting === engine.name
                    ? "시작 중"
                    : working
                      ? "다운로드 중"
                      : failed
                        ? "다시 시도"
                        : engine.ready
                          ? "다시 다운로드"
                          : "다운로드"}
                </button>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
