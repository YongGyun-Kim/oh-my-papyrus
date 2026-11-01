import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, Circle, RefreshCw } from "lucide-react";
import { api, message } from "../../lib/api";
import type { Readiness } from "../../lib/types";
import { AnalysisSettings } from "./AnalysisSettings";
import { CliConnections } from "./CliConnections";
import { ModelReadiness } from "./ModelReadiness";

const providers = {
  codex: "Codex",
  claude: "Claude Code",
  ollama: "Ollama",
  openai: "OpenAI API",
};

export function SettingsPage() {
  const [settings, setSettings] = useState<Readiness | null>(null);
  const [error, setError] = useState("");
  const [refreshCount, setRefreshCount] = useState(0);
  const revision = useRef(0);
  const mounted = useRef(true);
  const refresh = useCallback(async (signal?: AbortSignal) => {
    if (!mounted.current) return;
    const current = ++revision.current;
    try {
      const next = await api.settings(signal);
      if (!signal?.aborted && mounted.current && current === revision.current) {
        setSettings(next);
        setError("");
      }
    } catch (reason) {
      if (!signal?.aborted && mounted.current && current === revision.current)
        setError(message(reason));
    }
  }, []);
  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => {
      mounted.current = false;
      ++revision.current;
      controller.abort();
    };
  }, [refresh]);
  const connection = settings?.analysis_connection;
  return (
    <div className="page settings-page">
      <div className="page-heading">
        <div>
          <h1>설정</h1>
        </div>
        <button
          className="button secondary"
          onClick={() => {
            setRefreshCount((value) => value + 1);
            void refresh();
          }}
        >
          <RefreshCw size={14} />
          새로 고침
        </button>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {settings && (
        <section className="settings-section">
          <h2>실행 준비 상태</h2>
          <div className="engine-list">
            <div
              className="engine-row"
              role="group"
              aria-label="전사·분석 워커"
            >
              {settings.worker_running ? (
                <CheckCircle2 size={17} />
              ) : (
                <Circle size={17} />
              )}
              <div>
                <strong>전사·분석 워커</strong>
                {!settings.worker_running && (
                  <div className="model-guide">
                    <small>
                      서버 컴퓨터의 프로젝트 폴더에서 실행해 주세요.
                    </small>
                    <code>uv run --no-sync meetinglog worker</code>
                  </div>
                )}
              </div>
              <span className="status">
                {settings.worker_running ? "실행 중" : "실행 필요"}
              </span>
            </div>
            <div
              className="engine-row"
              role="group"
              aria-label="FFmpeg · FFprobe"
            >
              {settings.media_tools_ready ? (
                <CheckCircle2 size={17} />
              ) : (
                <Circle size={17} />
              )}
              <div>
                <strong>FFmpeg · FFprobe</strong>
                {!settings.media_tools_ready && (
                  <div className="model-guide">
                    <a
                      href="https://formulae.brew.sh/formula/ffmpeg"
                      target="_blank"
                      rel="noreferrer"
                    >
                      FFmpeg 설치 안내
                    </a>
                    <code>brew install ffmpeg</code>
                  </div>
                )}
              </div>
              <span className="status">
                {settings.media_tools_ready ? "준비됨" : "설치 필요"}
              </span>
            </div>
            {connection && (
              <div
                className="engine-row"
                role="group"
                aria-label="선택한 분석 도구"
              >
                {connection.ready ? (
                  <CheckCircle2 size={17} />
                ) : (
                  <Circle size={17} />
                )}
                <div>
                  <strong>선택한 분석 도구</strong>
                  <small>
                    {providers[connection.provider]}
                    {connection.model ? ` · ${connection.model}` : ""}
                  </small>
                  <small>
                    설정과 인증 상태예요. 실제 모델 응답은 대화 정리를 실행할 때
                    확인해요.
                  </small>
                </div>
                <span className="status">{connection.status}</span>
              </div>
            )}
          </div>
        </section>
      )}
      {settings ? (
        <ModelReadiness
          settings={settings}
          refreshCount={refreshCount}
          onChanged={refresh}
        />
      ) : (
        !error && <p className="empty-message">설정을 확인하고 있어요.</p>
      )}
      <AnalysisSettings refreshCount={refreshCount} onSaved={refresh} />
      <CliConnections refreshCount={refreshCount} onChange={refresh} />
    </div>
  );
}
