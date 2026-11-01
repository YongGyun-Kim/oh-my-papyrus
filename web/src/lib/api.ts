import type {
  EditRequest,
  AnalysisForm,
  CliConnection,
  CliProvider,
  FormOption,
  Job,
  Mode,
  Readiness,
  ModelDownload,
  SpeechModel,
  Recording,
  InputLimits,
  RecordingDetail,
  RecordingSummary,
  Transcript,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public status = 0,
    public code = "network_error",
  ) {
    super(message);
  }
}

function failure(body: unknown, status: number): ApiError {
  const error = (body as { error?: { message?: string; code?: string } })
    ?.error;
  return new ApiError(
    error?.message ?? "요청을 처리하지 못했어요. 다시 시도해 주세요.",
    status,
    error?.code,
  );
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, init);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new ApiError(
      "로컬 서버에 연결하지 못했어요. 서버가 실행 중인지 확인해 주세요.",
    );
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) throw failure(body, response.status);
  return body as T;
}
const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
const path = (id: string) => `/recordings/${encodeURIComponent(id)}`;

export const api = {
  inputLimits: (signal?: AbortSignal) =>
    request<InputLimits>("/recordings/limits", { signal }),
  listRecordings: async (signal?: AbortSignal) =>
    (await request<{ items: RecordingSummary[] }>("/recordings", { signal }))
      .items,
  detail: (id: string, signal?: AbortSignal) =>
    request<RecordingDetail>(path(id), { signal }),
  snapshotTranscript: async (id: string, transcriptId: string) =>
    (
      await request<{ transcript: Transcript }>(
        `${path(id)}/export?format=json&transcript_id=${encodeURIComponent(transcriptId)}`,
      )
    ).transcript,
  createDraft: (title: string) =>
    request<Recording>("/recordings/drafts", json("POST", { title })),
  putChunk: async (id: string, sequence: number, body: Blob) => {
    await request(`${path(id)}/chunks/${sequence}`, { method: "PUT", body });
  },
  finalize: (id: string, lastSequence: number) =>
    request<Recording>(
      `${path(id)}/finalize`,
      json("POST", { last_sequence: lastSequence }),
    ),
  upload: (
    file: File,
    onProgress?: (ratio: number) => void,
  ): Promise<Recording> =>
    new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/recordings");
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress?.(event.loaded / event.total);
      };
      xhr.onerror = () =>
        reject(
          new ApiError(
            "파일을 전송하지 못했어요. 로컬 서버 연결을 확인해 주세요.",
          ),
        );
      xhr.onload = () => {
        let body: unknown;
        try {
          body = JSON.parse(xhr.responseText);
        } catch {
          reject(failure(null, xhr.status));
          return;
        }
        if (xhr.status >= 200 && xhr.status < 300) resolve(body as Recording);
        else reject(failure(body, xhr.status));
      };
      const form = new FormData();
      form.append("file", file);
      xhr.send(form);
    }),
  analysisSettings: (signal?: AbortSignal) =>
    request<import("./types").AnalysisPreferences>("/settings/analysis", {
      signal,
    }),
  analysisOptions: (
    provider: import("./types").AnalysisPreferences["provider"],
    model: string,
    signal?: AbortSignal,
  ) =>
    request<import("./types").AnalysisOptions>(
      `/settings/analysis/options?provider=${encodeURIComponent(provider)}&model=${encodeURIComponent(model)}`,
      { signal },
    ),
  saveAnalysisSettings: (body: import("./types").AnalysisPreferences) =>
    request<import("./types").AnalysisPreferences>(
      "/settings/analysis",
      json("PATCH", body),
    ),
  forms: () => request<FormOption[]>("/recordings/analysis-forms"),
  settings: (signal?: AbortSignal) =>
    request<Readiness>("/settings", { signal }),
  modelDownload: (signal?: AbortSignal) =>
    request<ModelDownload>("/settings/models/download", { signal }),
  prepareModel: (model: SpeechModel) =>
    request<ModelDownload>(
      `/settings/models/${model}/download`,
      json("POST", {}),
    ),
  cliConnections: (signal?: AbortSignal) =>
    request<CliConnection[]>("/settings/cli-connections", { signal }),
  loginCli: (provider: CliProvider) =>
    request<CliConnection>(
      `/settings/cli-connections/${provider}/login`,
      json("POST", {}),
    ),
  cancelCliLogin: (provider: CliProvider) =>
    request<CliConnection>(
      `/settings/cli-connections/${provider}/cancel`,
      json("POST", {}),
    ),
  process: (id: string, mode: Mode) =>
    request<Job>(`${path(id)}/process`, json("POST", { mode })),
  analyze: (id: string, transcriptId: string, mode: Mode, form: AnalysisForm) =>
    request<Job>(
      `${path(id)}/analyze`,
      json("POST", { mode, transcript_id: transcriptId, form }),
    ),
  cancel: (jobId: string) =>
    request<Job>(`/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST",
    }),
  remove: (id: string) => request(path(id), { method: "DELETE" }),
  edit: (id: string, edit: EditRequest) =>
    request<Transcript>(`${path(id)}/transcript`, json("PATCH", edit)),
  renameSpeaker: (id: string, speakerId: string, name: string) =>
    request(
      `${path(id)}/speakers/${encodeURIComponent(speakerId)}`,
      json("PATCH", { display_name: name }),
    ),
};

export const message = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "처리하지 못했어요. 다시 시도해 주세요.";
export const clock = (ms: number) => {
  const seconds = Math.floor(Math.max(0, ms) / 1000);
  return `${Math.floor(seconds / 60)
    .toString()
    .padStart(2, "0")}:${(seconds % 60).toString().padStart(2, "0")}`;
};
