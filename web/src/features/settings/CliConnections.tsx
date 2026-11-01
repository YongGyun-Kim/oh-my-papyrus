import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, Circle } from "lucide-react";
import { api, message } from "../../lib/api";
import type { CliConnection, CliProvider } from "../../lib/types";

const tools = {
  codex: {
    name: "Codex",
    install: "https://learn.chatgpt.com/docs/codex/cli",
    command: "codex login",
  },
  claude: {
    name: "Claude Code",
    install: "https://code.claude.com/docs/en/setup",
    command: "claude auth login --claudeai",
  },
};
const labels: Record<CliConnection["state"], string> = {
  not_installed: "설치 필요",
  logged_out: "로그인 필요",
  connected: "로그인됨",
  logging_in: "로그인 대기 중",
  error: "확인 필요",
};

export function CliConnections({
  refreshCount,
  onChange,
}: {
  refreshCount: number;
  onChange?: () => void;
}) {
  const [connections, setConnections] = useState<CliConnection[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<CliProvider | null>(null);
  const revision = useRef(0);
  const load = useCallback(
    async (signal?: AbortSignal) => {
      const current = ++revision.current;
      try {
        const result = await api.cliConnections(signal);
        if (!signal?.aborted && current === revision.current) {
          setConnections(result);
          setError("");
          onChange?.();
        }
      } catch (reason) {
        if (!signal?.aborted && current === revision.current)
          setError(message(reason));
      }
    },
    [onChange],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [refreshCount, load]);

  const pending =
    connections?.some((item) => item.state === "logging_in") ?? false;
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

  const act = async (provider: CliProvider, cancel: boolean) => {
    setBusy(provider);
    ++revision.current;
    try {
      const result = await (cancel
        ? api.cancelCliLogin(provider)
        : api.loginCli(provider));
      setConnections(
        (items) =>
          items?.map((item) => (item.provider === provider ? result : item)) ??
          null,
      );
      setError("");
      onChange?.();
    } catch (reason) {
      setError(message(reason));
    } finally {
      ++revision.current;
      setBusy(null);
    }
  };

  return (
    <section className="settings-section">
      <h2>계정 연결</h2>
      <p>
        서버 컴퓨터에서 로그인 창이 열려요. 같은 컴퓨터의 브라우저에서 완료해
        주세요.
      </p>
      <p>로그인한 계정으로 대화를 분석해요. 인증 정보는 각 도구가 관리해요.</p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {connections ? (
        <div className="engine-list">
          {connections.map((connection) => {
            const tool = tools[connection.provider];
            const waiting = connection.state === "logging_in";
            return (
              <div
                className="engine-row cli-row"
                role="group"
                aria-label={tool.name}
                key={connection.provider}
              >
                {connection.state === "connected" ? (
                  <CheckCircle2 size={17} />
                ) : (
                  <Circle size={17} />
                )}
                <div>
                  <strong>{tool.name}</strong>
                  <small>
                    {connection.auth_method === "api_key" ? (
                      "API 키로 연결돼 있어요."
                    ) : connection.auth_method === "external" ? (
                      "외부 제공사 인증을 사용해요."
                    ) : waiting ? (
                      "로그인 대기는 5분 후 종료돼요."
                    ) : (
                      <>
                        터미널에서 로그인: <code>{tool.command}</code>
                      </>
                    )}
                  </small>
                  {connection.message && (
                    <small className="error">{connection.message}</small>
                  )}
                </div>
                <span className="status" role="status">
                  {labels[connection.state]}
                </span>
                <div className="cli-actions">
                  {connection.state === "not_installed" && (
                    <a href={tool.install} target="_blank" rel="noreferrer">
                      설치 안내
                    </a>
                  )}
                  <button
                    className="button secondary"
                    aria-label={`${tool.name} 로그인${waiting ? " 취소" : ""}`}
                    disabled={
                      busy !== null ||
                      connection.state === "connected" ||
                      connection.state === "not_installed"
                    }
                    onClick={() => void act(connection.provider, waiting)}
                  >
                    {busy === connection.provider
                      ? "처리 중"
                      : waiting
                        ? "로그인 취소"
                        : "로그인"}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        !error && <p>도구 연결 상태를 확인하고 있어요.</p>
      )}
    </section>
  );
}
