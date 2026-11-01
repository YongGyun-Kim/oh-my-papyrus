import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { SettingsPage } from "./SettingsPage";

afterEach(() => vi.unstubAllGlobals());

const connected = {
  provider: "codex",
  state: "connected",
  auth_method: "account",
  message: null,
};
const loggedOut = {
  provider: "claude",
  state: "logged_out",
  auth_method: null,
  message: null,
};

beforeEach(() => {
  vi.spyOn(api, "analysisSettings").mockResolvedValue({
    provider: "ollama",
    model: "gpt-oss:20b",
    reasoning: "low",
  });
  vi.spyOn(api, "analysisOptions").mockResolvedValue({
    models: ["gpt-oss:20b"],
    default_model: "gpt-oss:20b",
    reasoning: ["default", "low", "medium", "high"],
    message: null,
  });
  vi.spyOn(api, "settings").mockResolvedValue({
    mode: "local_only",
    api_configured: false,
    media_tools_ready: true,
    worker_running: true,
    engines: [],
  });
});

function server(respond: (path: string, method: string) => unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => ({
      ok: true,
      json: async () => respond(input, init?.method ?? "GET"),
    })),
  );
}

it("shows existing accounts and prevents starting login for an absent CLI", async () => {
  server(() => [connected, { ...loggedOut, state: "not_installed" }]);
  render(<SettingsPage />);
  const codex = await screen.findByRole("group", { name: "Codex" });
  expect(within(codex).getByText("로그인됨")).toBeVisible();
  expect(
    within(codex).getByRole("button", { name: "Codex 로그인" }),
  ).toBeDisabled();
  const claude = screen.getByRole("group", { name: "Claude Code" });
  expect(within(claude).getByText("설치 필요")).toBeVisible();
  expect(
    within(claude).getByRole("link", { name: "설치 안내" }),
  ).toHaveAttribute("href", expect.stringContaining("claude.com"));
  expect(
    within(claude).getByRole("button", { name: "Claude Code 로그인" }),
  ).toBeDisabled();
});

it("starts official login and updates its state when the browser flow finishes", async () => {
  let started = false;
  let polls = 0;
  server((path, method) => {
    if (method === "POST" && path.endsWith("/claude/login")) {
      started = true;
      return { ...loggedOut, state: "logging_in" };
    }
    return [
      connected,
      started
        ? { ...loggedOut, state: ++polls > 1 ? "connected" : "logging_in" }
        : loggedOut,
    ];
  });
  render(<SettingsPage />);
  await userEvent.click(
    await screen.findByRole("button", { name: "Claude Code 로그인" }),
  );
  expect(
    await screen.findByRole("button", { name: "Claude Code 로그인 취소" }),
  ).toBeVisible();
  const claude = screen.getByRole("group", { name: "Claude Code" });
  expect(
    await within(claude).findByText("로그인됨", {}, { timeout: 4000 }),
  ).toBeVisible();
  expect(screen.getByText(/서버 컴퓨터.*로그인 창/)).toBeVisible();
});

it("cancels a pending login without logging out an existing account", async () => {
  let cancelled = false;
  server((path, method) => {
    if (method === "POST" && path.endsWith("/claude/cancel")) {
      cancelled = true;
      return loggedOut;
    }
    return [
      connected,
      cancelled ? loggedOut : { ...loggedOut, state: "logging_in" },
    ];
  });
  render(<SettingsPage />);
  await userEvent.click(
    await screen.findByRole("button", { name: "Claude Code 로그인 취소" }),
  );
  expect(
    await screen.findByRole("button", { name: "Claude Code 로그인" }),
  ).toBeEnabled();
  expect(
    within(screen.getByRole("group", { name: "Codex" })).getByText("로그인됨"),
  ).toBeVisible();
});

it("keeps a login response when settings are refreshed during the request", async () => {
  let finishLogin!: (value: unknown) => void;
  let completed = false;
  let reads = 0;
  server((_path, method) => {
    if (method === "POST")
      return new Promise((resolve) => {
        finishLogin = resolve;
      });
    reads++;
    return [
      connected,
      completed ? { ...loggedOut, state: "connected" } : loggedOut,
    ];
  });
  render(<SettingsPage />);
  await userEvent.click(
    await screen.findByRole("button", { name: "Claude Code 로그인" }),
  );
  const beforeRefresh = reads;
  await userEvent.click(screen.getByRole("button", { name: "새로 고침" }));
  expect(reads).toBeGreaterThan(beforeRefresh);
  await act(async () => finishLogin({ ...loggedOut, state: "logging_in" }));
  expect(
    await screen.findByRole("button", { name: "Claude Code 로그인 취소" }),
  ).toBeEnabled();
  completed = true;
  expect(
    await within(screen.getByRole("group", { name: "Claude Code" })).findByText(
      "로그인됨",
      {},
      { timeout: 2500 },
    ),
  ).toBeVisible();
});

it("reports login start failures and lets the user retry", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: string, init?: RequestInit) => ({
      ok: init?.method !== "POST",
      status: init?.method === "POST" ? 409 : 200,
      json: async () =>
        init?.method === "POST"
          ? {
              error: {
                code: "cli_login_failed",
                message: "로그인을 시작하지 못했어요.",
              },
            }
          : [connected, loggedOut],
    })),
  );
  render(<SettingsPage />);
  await userEvent.click(
    await screen.findByRole("button", { name: "Claude Code 로그인" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "로그인을 시작하지 못했어요.",
  );
  expect(
    screen.getByRole("button", { name: "Claude Code 로그인" }),
  ).toBeEnabled();
});

it("refreshes CLI status from the settings page refresh button", async () => {
  let signedIn = false;
  server(() => [
    connected,
    signedIn ? { ...loggedOut, state: "connected" } : loggedOut,
  ]);
  render(<SettingsPage />);
  await screen.findByRole("button", { name: "Claude Code 로그인" });
  signedIn = true;
  await userEvent.click(screen.getByRole("button", { name: "새로 고침" }));
  expect(
    await within(screen.getByRole("group", { name: "Claude Code" })).findByText(
      "로그인됨",
    ),
  ).toBeVisible();
});
