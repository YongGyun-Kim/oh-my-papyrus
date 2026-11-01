import { useEffect, useState } from "react";
import { api, message } from "../../lib/api";
import type { AnalysisPreferences, AnalysisOptions } from "../../lib/types";

const providers = {
  ollama: "Ollama (로컬)",
  codex: "Codex",
  claude: "Claude Code",
  openai: "OpenAI API",
};
const levels: Record<string, string> = {
  default: "모델 기본값",
  off: "끄기",
  on: "켜기",
  none: "없음",
  minimal: "최소",
  low: "낮음",
  medium: "보통",
  high: "높음",
  xhigh: "매우 높음",
  max: "최대",
  ultra: "Ultra",
};

export function AnalysisSettings({
  refreshCount,
  onSaved,
}: {
  refreshCount: number;
  onSaved?: () => void;
}) {
  const [saved, setSaved] = useState<AnalysisPreferences | null>(null);
  const [draft, setDraft] = useState<AnalysisPreferences | null>(null);
  const [options, setOptions] = useState<AnalysisOptions | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void api
      .analysisSettings(controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) {
          setSaved(result);
          setDraft(result);
          setError("");
          setStatus("");
        }
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(message(reason));
      });
    return () => controller.abort();
  }, [refreshCount]);
  const provider = draft?.provider,
    model = draft?.model;
  const cli = provider === "codex" || provider === "claude";
  const queryModel = cli ? "" : model;
  useEffect(() => {
    if (!provider) return;
    const controller = new AbortController();
    setOptions(null);
    const timer = setTimeout(() => {
      void api
        .analysisOptions(provider, queryModel ?? "", controller.signal)
        .then((result) => {
          if (!controller.signal.aborted) setOptions(result);
        })
        .catch((reason) => {
          if (!controller.signal.aborted) setError(message(reason));
        });
    }, 200);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [provider, queryModel, refreshCount]);
  const catalog = options?.catalog ?? [];
  const selected = catalog.find((item) =>
    [item.id, ...(item.aliases ?? [])].includes(
      draft?.model || options?.default_model || "",
    ),
  );
  const reasoning = cli
    ? ["default", ...(selected?.reasoning ?? [])]
    : (options?.reasoning ?? ["default"]);
  const unsupportedModel =
    cli && catalog.length > 0 && !!draft?.model && !selected;
  const unsupportedReasoning =
    !!options && !!draft && !reasoning.includes(draft.reasoning);
  const canSave = !!options && !unsupportedModel && !unsupportedReasoning;
  const changeModel = (value: string) => {
    if (!draft) return;
    if (!cli) setOptions(null);
    setDraft({ ...draft, model: value, reasoning: "default" });
    setStatus("");
  };
  const save = async () => {
    if (!draft || !options || !canSave) return;
    setBusy(true);
    setError("");
    setStatus("");
    try {
      const result = await api.saveAnalysisSettings({
        ...draft,
        model: draft.model || options.default_model,
      });
      setSaved(result);
      setDraft(result);
      setStatus("설정을 저장했어요. 다음 분석부터 적용해요.");
      onSaved?.();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="settings-section">
      <h2>대화 분석 모델</h2>
      <p>
        분석 도구와 기본 모델을 선택해 주세요. 전사 설정에는 영향을 주지 않아요.
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {draft ? (
        <form
          className="analysis-settings-form"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <label>
            분석 도구
            <select
              value={draft.provider}
              disabled={busy}
              onChange={(event) => {
                setOptions(null);
                setDraft({
                  provider: event.target
                    .value as AnalysisPreferences["provider"],
                  model: "",
                  reasoning: "default",
                });
                setStatus("");
                setError("");
              }}
            >
              {Object.entries(providers).map(([id, title]) => (
                <option key={id} value={id}>
                  {title}
                </option>
              ))}
            </select>
          </label>
          <label>
            모델
            {cli && catalog.length > 0 ? (
              <select
                value={selected && draft.model ? selected.id : draft.model}
                disabled={busy || !options}
                onChange={(event) => changeModel(event.target.value)}
              >
                <option value="">도구 기본 모델</option>
                {unsupportedModel && (
                  <option value={draft.model} disabled>
                    {draft.model} (목록에 없음)
                  </option>
                )}
                {catalog.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            ) : (
              <>
                <input
                  type="text"
                  list="analysis-models"
                  value={draft.model}
                  disabled={busy}
                  maxLength={128}
                  placeholder={options?.default_model || "도구 기본 모델"}
                  onChange={(event) => changeModel(event.target.value)}
                />
                <datalist id="analysis-models">
                  {options?.models.map((name) => (
                    <option key={name} value={name} />
                  ))}
                </datalist>
              </>
            )}
          </label>
          <label>
            추론 수준
            <select
              value={unsupportedReasoning ? "" : draft.reasoning}
              disabled={busy || !options}
              onChange={(event) => {
                setDraft({
                  ...draft,
                  reasoning: event.target
                    .value as AnalysisPreferences["reasoning"],
                });
                setStatus("");
              }}
            >
              {unsupportedReasoning && (
                <option value="" disabled>
                  다시 선택해 주세요
                </option>
              )}
              {reasoning.map((level) => (
                <option key={level} value={level}>
                  {level === "default" && selected?.default_reasoning
                    ? `모델 기본값 (${levels[selected.default_reasoning] ?? selected.default_reasoning})`
                    : (levels[level] ?? level)}
                </option>
              ))}
            </select>
          </label>
          {unsupportedModel && (
            <p className="error">
              저장된 모델이 현재 목록에 없어요. 사용할 모델을 다시 선택해
              주세요.
            </p>
          )}
          {unsupportedReasoning && (
            <p className="error">
              저장된 추론 수준을 이 모델에서 사용할 수 없어요. 다시 선택해
              주세요.
            </p>
          )}
          <p className="help left">
            {cli
              ? catalog.length > 0
                ? "연결된 도구에서 가져온 모델과 각 모델이 지원하는 추론 수준을 표시해요."
                : "모델 목록을 조회할 수 없으면 이름을 직접 입력할 수 있어요. 추론 수준은 기본값만 사용해요."
              : "목록에서 고르거나 모델 이름을 입력할 수 있어요."}
          </p>
          {options?.message && <p className="help left">{options.message}</p>}
          {draft.provider !== "ollama" && (
            <p className="help left">
              전사 텍스트를 선택한 도구의 제공사로 보내요. 음성 파일은 보내지
              않아요.
            </p>
          )}
          {draft.provider === "openai" && (
            <p className="help left">
              API 키는 서버의 OPENAI_API_KEY 환경변수에 설정해 주세요.
            </p>
          )}
          <div className="analysis-settings-actions">
            <button
              className="button"
              type="submit"
              disabled={
                busy ||
                !canSave ||
                JSON.stringify(saved) === JSON.stringify(draft)
              }
            >
              {busy ? "저장 중" : "저장"}
            </button>
            {status && <p role="status">{status}</p>}
          </div>
        </form>
      ) : (
        !error && <p>분석 설정을 확인하고 있어요.</p>
      )}
    </section>
  );
}
