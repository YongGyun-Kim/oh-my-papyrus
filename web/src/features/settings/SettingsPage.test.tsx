import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { SettingsPage } from "./SettingsPage";

beforeEach(() => {
  vi.spyOn(api, "modelDownload").mockResolvedValue({
    model: null,
    state: "idle",
    completed: 0,
    total: null,
    error_message: null,
  });
  vi.spyOn(api, "analysisSettings").mockResolvedValue({
    provider: "ollama",
    model: "gpt-oss:20b",
    reasoning: "default",
  });
  vi.spyOn(api, "analysisOptions").mockResolvedValue({
    models: [],
    reasoning: ["default"],
    catalog: [],
    default_model: "gpt-oss:20b",
  });
  vi.spyOn(api, "cliConnections").mockResolvedValue([]);
});

it("ignores an older readiness response arriving after a newer refresh", async () => {
  const old = {
    mode: "local_only" as const,
    api_configured: false,
    media_tools_ready: true,
    worker_running: false,
    engines: [],
  };
  vi.spyOn(api, "settings").mockResolvedValue(old);
  render(<SettingsPage />);
  const worker = await screen.findByRole("group", { name: "전사·분석 워커" });
  expect(within(worker).getByText("실행 필요")).toBeVisible();
  let finishOld!: (value: typeof old) => void;
  vi.mocked(api.settings)
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishOld = resolve;
        }),
    )
    .mockResolvedValue({ ...old, worker_running: true });
  await userEvent.click(screen.getByRole("button", { name: "새로 고침" }));
  await waitFor(() =>
    expect(within(worker).getByText("실행 중")).toBeVisible(),
  );
  await act(async () => {
    finishOld(old);
  });
  expect(within(worker).getByText("실행 중")).toBeVisible();
});

it("shows the worker and selected analysis tool independently from voice model readiness", async () => {
  vi.spyOn(api, "settings").mockResolvedValue({
    mode: "local_only",
    api_configured: false,
    media_tools_ready: true,
    worker_running: false,
    engines: [],
    analysis_connection: {
      provider: "codex",
      model: "selected-model",
      ready: true,
      status: "로그인됨",
    },
  });
  render(<SettingsPage />);
  const worker = await screen.findByRole("group", { name: "전사·분석 워커" });
  expect(within(worker).getByText("실행 필요")).toBeVisible();
  expect(
    within(worker).getByText("uv run --no-sync meetinglog worker"),
  ).toBeVisible();
  const analysis = screen.getByRole("group", { name: "선택한 분석 도구" });
  expect(within(analysis).getByText(/Codex/)).toBeVisible();
  expect(within(analysis).getByText("로그인됨")).toBeVisible();
});

it("starts model download and shows retry after a safe failure", async () => {
  vi.spyOn(api, "settings").mockResolvedValue({
    mode: "local_only",
    api_configured: false,
    media_tools_ready: true,
    worker_running: true,
    engines: [
      {
        name: "vad",
        repo_id: "mlx-community/silero-vad",
        ready: false,
        quality: "unverified",
      },
    ],
  });
  vi.spyOn(api, "prepareModel")
    .mockResolvedValueOnce({
      model: "vad",
      state: "failed",
      completed: 1,
      total: 3,
      error_message: "다운로드를 완료하지 못했어요.",
    })
    .mockResolvedValueOnce({
      model: "vad",
      state: "downloading",
      completed: 1,
      total: 2,
      error_message: null,
    });
  render(<SettingsPage />);
  const vad = await screen.findByRole("group", { name: "음성 구간 탐지" });
  await userEvent.click(within(vad).getByRole("button", { name: "다운로드" }));
  expect(within(vad).getByRole("alert")).toHaveTextContent(
    "다운로드를 완료하지 못했어요.",
  );
  await userEvent.click(within(vad).getByRole("button", { name: "다시 시도" }));
  expect(within(vad).getByRole("progressbar")).toHaveAttribute("value", "1");
  expect(within(vad).getByText("50% · 1/2 파일")).toBeVisible();
  expect(
    within(vad).getByRole("button", { name: "다운로드 중" }),
  ).toBeDisabled();
  expect(api.prepareModel).toHaveBeenLastCalledWith("vad");
});

it("polls an existing download after reopening without resetting analysis edits", async () => {
  const settings = {
    mode: "local_only" as const,
    api_configured: false,
    media_tools_ready: true,
    worker_running: true,
    engines: [
      {
        name: "vad",
        repo_id: "mlx-community/silero-vad",
        ready: false,
        quality: "unverified",
      },
    ],
  };
  vi.spyOn(api, "settings").mockResolvedValue(settings);
  vi.mocked(api.modelDownload)
    .mockResolvedValueOnce({
      model: "vad",
      state: "downloading",
      completed: 1,
      total: 2,
      error_message: null,
    })
    .mockResolvedValue({
      model: "vad",
      state: "succeeded",
      completed: 2,
      total: 2,
      error_message: null,
    });
  render(<SettingsPage />);
  const model = await screen.findByLabelText("모델", { exact: true });
  await userEvent.clear(model);
  await userEvent.type(model, "my-unsaved-model");
  vi.mocked(api.settings).mockResolvedValue({
    ...settings,
    engines: [{ ...settings.engines[0], ready: true }],
  });
  const vad = screen.getByRole("group", { name: "음성 구간 탐지" });
  await waitFor(() => expect(within(vad).getByText("준비됨")).toBeVisible(), {
    timeout: 4000,
  });
  expect(model).toHaveValue("my-unsaved-model");
});

it("shows installation commands for missing models and links to the configured downloads", async () => {
  vi.spyOn(api, "settings").mockResolvedValue({
    mode: "local_only",
    api_configured: false,
    media_tools_ready: false,
    worker_running: false,
    engines: [
      {
        name: "asr",
        repo_id: "mlx-community/Qwen3-ASR-1.7B-8bit",
        ready: true,
        quality: "unverified",
      },
      {
        name: "vad",
        repo_id: "mlx-community/silero-vad",
        ready: false,
        quality: "unverified",
      },
      {
        name: "analysis",
        repo_id: "qwen3:8b",
        ready: false,
        quality: "unverified",
      },
    ],
  });
  vi.spyOn(api, "cliConnections").mockResolvedValue([]);
  render(<SettingsPage />);
  const vad = await screen.findByRole("group", { name: "음성 구간 탐지" });
  expect(
    within(vad).getByText(
      "uv run --extra speech meetinglog prepare-models --models vad",
    ),
  ).toBeVisible();
  expect(within(vad).getByRole("link")).toHaveAttribute(
    "href",
    "https://huggingface.co/mlx-community/silero-vad",
  );
  const asr = screen.getByRole("group", { name: "한국어 전사" });
  expect(within(asr).queryByText(/prepare-models/)).not.toBeInTheDocument();
  const analysis = screen.getByRole("group", { name: "대화 분석" });
  expect(within(analysis).getByText("ollama pull qwen3:8b")).toBeVisible();
  expect(
    within(analysis).getByRole("link", { name: "qwen3:8b" }),
  ).toHaveAttribute("href", "https://ollama.com/library/qwen3");
  expect(screen.getByText("brew install ffmpeg")).toBeVisible();
});
