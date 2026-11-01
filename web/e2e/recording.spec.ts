import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";

test("connects CLI accounts from settings on desktop and mobile", async ({
  page,
}) => {
  let loggingIn = false;
  let polls = 0;
  await page.route("**/api/settings/cli-connections**", async (route) => {
    const codex = {
      provider: "codex",
      state: "connected",
      auth_method: "account",
      message: null,
    };
    const claude = {
      provider: "claude",
      state: "logged_out",
      auth_method: null,
      message: null,
    };
    if (route.request().method() === "POST") {
      expect(route.request().url()).toMatch(/\/claude\/login$/);
      expect(route.request().postDataJSON()).toEqual({});
      loggingIn = true;
      await route.fulfill({ json: { ...claude, state: "logging_in" } });
    } else {
      await route.fulfill({
        json: [
          codex,
          loggingIn
            ? { ...claude, state: ++polls > 1 ? "connected" : "logging_in" }
            : claude,
        ],
      });
    }
  });
  await page.goto("/#settings");
  await expect(
    page.getByRole("heading", { name: "대화 분석 모델" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Codex 로그인", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Claude Code 로그인", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Claude Code 로그인 취소", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("group", { name: "Claude Code" }).getByRole("status"),
  ).toHaveText("로그인됨");
  await page.screenshot({
    path: "test-results/cli-login-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("button", { name: "Claude Code 로그인", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/cli-login-mobile.png",
    fullPage: true,
  });
});

function wav() {
  const length = 16000 * 6 * 2;
  const buffer = Buffer.alloc(44 + length);
  buffer.write("RIFF", 0);
  buffer.writeUInt32LE(length + 36, 4);
  buffer.write("WAVEfmt ", 8);
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(1, 22);
  buffer.writeUInt32LE(16000, 24);
  buffer.writeUInt32LE(32000, 28);
  buffer.writeUInt16LE(2, 32);
  buffer.writeUInt16LE(16, 34);
  buffer.write("data", 36);
  buffer.writeUInt32LE(length, 40);
  return buffer;
}

test("checks setup readiness and retries model downloads on desktop and mobile", async ({
  page,
}) => {
  let attempts = 0,
    polls = 0,
    prepared = false;
  let download = {
    model: null as string | null,
    state: "idle",
    completed: 0,
    total: null as number | null,
    error_message: null as string | null,
  };
  await page.route("**/api/settings", async (route) => {
    const response = await route.fetch();
    const settings = await response.json();
    settings.worker_running = true;
    settings.media_tools_ready = true;
    settings.engines = [
      {
        name: "asr",
        repo_id: "mlx-community/Qwen3-ASR-1.7B-8bit",
        ready: true,
        quality: "unverified",
      },
      {
        name: "vad",
        repo_id: "mlx-community/silero-vad",
        ready: prepared,
        quality: "unverified",
      },
    ];
    await route.fulfill({ response, json: settings });
  });
  await page.route("**/api/settings/cli-connections", (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route("**/api/settings/models/download", async (route) => {
    if (download.state === "downloading" && ++polls >= 3) {
      if (attempts === 1)
        download = {
          ...download,
          state: "failed",
          error_message: "모델을 받지 못했어요. 다시 시도해 주세요.",
        };
      else {
        prepared = true;
        download = { ...download, state: "succeeded", completed: 2 };
      }
    }
    await route.fulfill({ json: download });
  });
  await page.route("**/api/settings/models/vad/download", async (route) => {
    expect(route.request().method()).toBe("POST");
    expect(route.request().postDataJSON()).toEqual({});
    attempts += 1;
    polls = 0;
    download = {
      model: "vad",
      state: "downloading",
      completed: 1,
      total: 2,
      error_message: null,
    };
    await route.fulfill({ json: download });
  });
  await page.goto("/#settings");
  await expect(
    page.getByRole("group", { name: "전사·분석 워커" }).getByText("실행 중"),
  ).toBeVisible();
  const vad = page.getByRole("group", { name: "음성 구간 탐지", exact: true });
  await vad.getByRole("button", { name: "다운로드", exact: true }).click();
  await expect(vad.getByRole("progressbar")).toHaveAttribute("value", "1");
  await expect(vad.getByText("50% · 1/2 파일")).toBeVisible();
  await page.screenshot({
    path: "test-results/model-download-desktop.png",
    fullPage: true,
  });
  await expect(vad.getByRole("alert")).toHaveText(
    "모델을 받지 못했어요. 다시 시도해 주세요.",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await vad
    .getByRole("button", { name: "다시 시도", exact: true })
    .scrollIntoViewIfNeeded();
  expect(
    (await vad.locator(":scope > div").first().boundingBox())!.width,
  ).toBeGreaterThan(200);
  await page.screenshot({
    path: "test-results/model-download-mobile.png",
    fullPage: true,
  });
  await vad.getByRole("button", { name: "다시 시도", exact: true }).click();
  await page.reload();
  await expect(vad.getByRole("progressbar")).toHaveAttribute("value", "1");
  await expect(vad.getByText("준비됨", { exact: true })).toBeVisible();
  await expect(
    vad.getByRole("button", { name: "다시 다운로드", exact: true }),
  ).toBeEnabled();
  expect(attempts).toBe(2);
});

test("shows speech processing steps and progress on desktop and mobile", async ({
  page,
}) => {
  const response = await page.request.post("/api/recordings", {
    multipart: {
      file: { name: "진행 상태.wav", mimeType: "audio/wav", buffer: wav() },
    },
  });
  expect(response.ok()).toBe(true);
  const recording = await response.json();
  let phase = "normalize";
  let state = "running";
  await page.route(`**/api/recordings/${recording.id}`, async (route) => {
    const response = await route.fetch();
    const detail = await response.json();
    detail.job = { ...detail.job, state, stage: "speech" };
    detail.processing_history = [
      {
        job_id: detail.job.id,
        kind: "process",
        mode: "local_only",
        state,
        stage: "speech",
        event: "speech_progress",
        created_at: new Date().toISOString(),
        metadata: {
          phase,
          completed: phase === "asr" ? 2 : 0,
          total: phase === "asr" ? 4 : null,
        },
      },
    ];
    await route.fulfill({ response, json: detail });
  });
  await page.goto(`/#record/${recording.id}`);
  const progress = page.getByRole("progressbar", { name: "현재 단계 진행률" });
  await expect(page.getByText("음성 파일을 준비하고 있어요.")).toBeVisible();
  await expect(progress).not.toHaveAttribute("value");
  for (const [next, label, step] of [
    ["vad", "대화가 있는 구간을 찾고 있어요.", "2/6 단계"],
    ["asr", "음성을 글로 바꾸고 있어요.", "3/6 단계"],
    ["align", "문장의 재생 위치를 맞추고 있어요.", "4/6 단계"],
    ["diarize", "화자를 구분하고 있어요.", "5/6 단계"],
    ["assemble", "전사 결과를 정리하고 저장하고 있어요.", "6/6 단계"],
  ]) {
    phase = next;
    await expect(page.getByText(label, { exact: true })).toBeVisible();
    await expect(page.getByText(step, { exact: true })).toBeVisible();
    if (phase === "asr") {
      await expect(progress).toHaveAttribute("value", "2");
      await expect(page.getByText("50% · 2/4 구간")).toBeVisible();
      await page.screenshot({
        path: "test-results/processing-desktop.png",
        fullPage: true,
      });
      await page.setViewportSize({ width: 390, height: 844 });
      await expect(progress).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      ).toBe(true);
      await expect(
        page.getByRole("button", { name: "처리 취소", exact: true }),
      ).toBeVisible();
      await page.screenshot({
        path: "test-results/processing-mobile.png",
        fullPage: true,
      });
    }
  }
  state = "succeeded";
  await expect(progress).toHaveCount(0);
});

test("imports, edits, reanalyzes, seeks, exports and retains a conversation", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "파일 가져오기", exact: true })
    .click();
  await page.getByLabel("녹음 파일", { exact: true }).setInputFiles({
    name: "브라우저 검증.wav",
    mimeType: "audio/wav",
    buffer: wav(),
  });
  await page.getByRole("button", { name: "대화 정리", exact: true }).click();
  await page.getByLabel("정리 양식", { exact: true }).selectOption("interview");
  await page.getByRole("button", { name: "정리 시작", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "사용자 상황", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("언제 서비스를 시작할까요?", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "화자 정보", exact: true }).click();
  await page.getByLabel("화자 1 이름").fill("인터뷰어");
  await page.getByLabel("화자 1 역할").fill("질문자");
  await page.getByRole("button", { name: "저장", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "00:00 인터뷰어 발언 듣기" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "발언 수정", exact: true })
    .first()
    .click();
  await page
    .getByLabel("발언 내용", { exact: true })
    .fill("서비스는 언제 시작할까요?");
  await page.getByRole("button", { name: "수정 저장", exact: true }).click();
  await expect(page.getByText(/수정 전 전사를 바탕으로/)).toBeVisible();
  await page
    .getByRole("button", { name: "다시 정리", exact: true })
    .last()
    .click();
  await page.getByLabel("정리 양식", { exact: true }).selectOption("project");
  await page.getByRole("button", { name: "정리 시작", exact: true }).click();
  await expect(page.getByText(/수정 전 전사를 바탕으로/)).not.toBeVisible();
  const after = await (
    await page.request.get(`/api/recordings/${page.url().split("#record/")[1]}`)
  ).json();
  expect(after.analysis.form).toBe("project");
  await expect(
    page.getByRole("button", { name: "근거 문장 t2", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "근거 보기", exact: true }).click();
  await page
    .getByRole("button", { name: "근거 문장 t2", exact: true })
    .first()
    .click();
  await expect(page.getByTestId("sentence-t2")).toHaveAttribute(
    "aria-current",
    "true",
  );
  await expect
    .poll(() =>
      page.locator("audio").evaluate((element) => element.currentTime),
    )
    .toBeCloseTo(2.2, 1);
  await page.getByText("내보내기", { exact: true }).click();
  const summaryPromise = page.waitForEvent("download");
  await page
    .getByRole("link", { name: "대화 정리 · Markdown", exact: true })
    .click();
  const summaryDownload = await summaryPromise;
  expect(summaryDownload.suggestedFilename()).toMatch(/-analysis\.md$/);
  const summary = await readFile((await summaryDownload.path())!, "utf8");
  expect(summary).toContain("서비스 시작 일정을 논의했다.");
  expect(summary).not.toContain("기록 ID:");
  expect(summary).not.toContain("근거:");
  expect(summary).not.toContain("## 전사");
  const markdownPromise = page.waitForEvent("download");
  await page
    .getByRole("link", { name: "Markdown · 에이전트 전달용", exact: true })
    .click();
  const markdownDownload = await markdownPromise;
  expect(markdownDownload.suggestedFilename()).toMatch(/\.md$/);
  const markdown = await readFile((await markdownDownload.path())!, "utf8");
  expect(markdown).toContain("기록 ID:");
  expect(markdown).toContain("분석 기준 전사:");
  expect(markdown).toContain("#### t2");
  expect(markdown).toContain("인터뷰어");
  expect(markdown).toContain("수정문: 서비스는 언제 시작할까요?");
  expect(markdown).toContain("자동 전사 원문: 언제 서비스를 시작할까요?");
  const downloadPromise = page.waitForEvent("download");
  await page
    .getByRole("link", { name: "JSON · AI 분석용", exact: true })
    .click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.json$/);
  const path = page.url();
  await page.reload();
  await expect(
    page.getByText("서비스는 언제 시작할까요?", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "00:00 인터뷰어 발언 듣기" }),
  ).toBeVisible();
  for (const size of [
    { width: 1440, height: 900 },
    { width: 1280, height: 800 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(size);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
  await page.goto(path);
});

test("plays a transcript sentence until the next sentence and allows continuous playback", async ({
  page,
}) => {
  const response = await page.request.post("/api/recordings", {
    multipart: {
      file: {
        name: "문장 재생 검증.wav",
        mimeType: "audio/wav",
        buffer: wav(),
      },
    },
  });
  const recording = await response.json();
  await page.goto(`/#record/${recording.id}`);
  const audio = page.locator("audio");
  await expect
    .poll(() => audio.evaluate((element) => element.readyState))
    .toBeGreaterThanOrEqual(1);
  await page
    .getByRole("button", { name: /발언 듣기/ })
    .first()
    .click();
  await expect
    .poll(() => audio.evaluate((element) => element.paused))
    .toBe(false);
  await expect
    .poll(() => audio.evaluate((element) => element.currentTime))
    .toBeGreaterThan(0.2);
  await expect
    .poll(() => audio.evaluate((element) => element.paused))
    .toBe(true);
  expect(await audio.evaluate((element) => element.currentTime)).toBeCloseTo(
    2.2,
    2,
  );
  await audio.evaluate((element) => element.play());
  await expect
    .poll(() => audio.evaluate((element) => element.currentTime))
    .toBeGreaterThan(2.4);
  await page.getByTestId("sentence-t2").locator(".sentence-text").click();
  await expect
    .poll(() => audio.evaluate((element) => element.paused))
    .toBe(false);
  await expect
    .poll(() => audio.evaluate((element) => element.paused))
    .toBe(true);
  expect(await audio.evaluate((element) => element.currentTime)).toBeCloseTo(
    5,
    2,
  );
});

test("captures fake microphone audio and finalizes before processing", async ({
  page,
}) => {
  await page.addInitScript(() => {
    const state = window as unknown as { audioMetadata: number[] };
    state.audioMetadata = [];
    document.addEventListener(
      "loadedmetadata",
      (event) => {
        if (event.target instanceof HTMLAudioElement)
          state.audioMetadata.push(event.target.duration);
      },
      true,
    );
  });
  await page.goto("/");
  await page.getByRole("button", { name: "녹음 시작", exact: true }).click();
  await expect(page.getByText("00:01", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "녹음 종료", exact: true }).click();
  await page.getByRole("button", { name: "대화 정리", exact: true }).click();
  await page.getByLabel("정리 양식", { exact: true }).selectOption("interview");
  await page.getByRole("button", { name: "정리 시작", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "사용자 상황", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "화자 정보", exact: true }),
  ).toBeVisible();
  const id = page.url().split("#record/")[1];
  const result = await page.request.get(`/api/recordings/${id}`);
  const detail = await result.json();
  expect(detail.recording.source).toBe("microphone");
  expect(detail.recording.input_state).toBe("ready");
  await expect
    .poll(async () => {
      const current = await (
        await page.request.get(`/api/recordings/${id}`)
      ).json();
      return current.job.state;
    })
    .toBe("succeeded");
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (window as unknown as { audioMetadata: number[] }).audioMetadata
            .length,
      ),
    )
    .toBeGreaterThan(0);
  expect(
    await page.evaluate(() =>
      (window as unknown as { audioMetadata: number[] }).audioMetadata.every(
        Number.isFinite,
      ),
    ),
  ).toBe(true);
  const audio = page.locator("audio");
  const duration = await audio.evaluate((element) => element.duration);
  expect(duration).toBeGreaterThan(0);
  expect(Math.abs(duration - detail.recording.duration_ms / 1000)).toBeLessThan(
    0.15,
  );
  await audio.evaluate(async (element) => {
    element.currentTime = element.duration / 2;
    await element.play();
  });
  await expect
    .poll(() => audio.evaluate((element) => element.ended))
    .toBe(true);
  expect(await audio.evaluate((element) => element.duration)).toBeCloseTo(
    duration,
    2,
  );
});
test("preserves an edit while scrolling a long virtual transcript", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() => {
    const state = window as unknown as { layoutErrors: string[] };
    state.layoutErrors = [];
    window.addEventListener("error", (event) =>
      state.layoutErrors.push(event.message),
    );
  });
  const response = await page.request.post("/api/recordings", {
    multipart: {
      file: { name: "긴 전사 검증.wav", mimeType: "audio/wav", buffer: wav() },
    },
  });
  const recording = await response.json();
  await page.route(`**/api/recordings/${recording.id}`, async (route) => {
    const response = await route.fetch();
    const detail = await response.json();
    if (detail.transcript?.turns.length) {
      const source = detail.transcript.turns[0];
      detail.transcript.turns.push(
        ...Array.from({ length: 500 }, (_, index) => ({
          ...source,
          id: `extra-${index}`,
          sentences: [
            {
              ...source.sentences[0],
              id: `extra-sentence-${index}`,
              text_original: `긴 전사 시험 발언 ${index}`,
            },
          ],
        })),
      );
    }
    await route.fulfill({ response, json: detail });
  });
  await page.goto(`/#record/${recording.id}`);
  await page
    .getByRole("button", { name: "발언 수정", exact: true })
    .first()
    .click();
  await page
    .getByLabel("발언 내용", { exact: true })
    .fill("스크롤 후에도 남아야 하는 초안");
  await page.locator(".transcript-scroll").evaluate((element) => {
    element.scrollTop = 30_000;
  });
  await expect(page.getByTestId("sentence-t1")).not.toBeAttached();
  await page.locator(".transcript-scroll").evaluate((element) => {
    element.scrollTop = 0;
  });
  await expect(page.getByLabel("발언 내용", { exact: true })).toHaveValue(
    "스크롤 후에도 남아야 하는 초안",
  );
  expect(errors).toEqual([]);
  expect(
    await page.evaluate(
      () => (window as unknown as { layoutErrors: string[] }).layoutErrors,
    ),
  ).toEqual([]);
});

test("shows decision comparisons and form preview on desktop and mobile", async ({
  page,
}) => {
  const uploaded = await page.request.post("/api/recordings", {
    multipart: {
      file: { name: "선택지 검증.wav", mimeType: "audio/wav", buffer: wav() },
    },
  });
  expect(uploaded.ok()).toBe(true);
  const record = await uploaded.json();
  await expect
    .poll(
      async () => {
        const detail = await (
          await page.request.get(`/api/recordings/${record.id}`)
        ).json();
        return !!detail.transcript;
      },
      { timeout: 20000 },
    )
    .toBe(true);
  await page.goto(`/#record/${record.id}`);
  await page.getByRole("button", { name: "대화 정리", exact: true }).click();
  await page.getByLabel("정리 양식", { exact: true }).selectOption("decision");
  await expect(page.getByRole("list", { name: "정리할 항목" })).toContainText(
    "선택지 비교",
  );
  await page.getByRole("button", { name: "정리 시작", exact: true }).click();
  const table = page.getByRole("table", { name: "선택지 비교" });
  await expect(table).toBeVisible();
  await expect(table).toContainText("다음 주 시작");
  await expect(
    page.getByRole("button", { name: "근거 문장 t1", exact: true }),
  ).toHaveCount(0);
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await table.scrollIntoViewIfNeeded();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `test-results/analysis-decision-${width}.png`,
      fullPage: true,
    });
  }
});

test("saves analysis model and effort independently on desktop and mobile", async ({
  page,
}) => {
  await page.route("**/api/settings/cli-connections", (route) =>
    route.fulfill({
      json: [
        {
          provider: "codex",
          state: "connected",
          auth_method: "account",
          message: null,
        },
        {
          provider: "claude",
          state: "connected",
          auth_method: "account",
          message: null,
        },
      ],
    }),
  );
  await page.goto("/#settings");
  await page.getByLabel("분석 도구").selectOption("claude");
  await page
    .getByRole("option", { name: "Sonnet (테스트)" })
    .waitFor({ state: "attached" });
  await page
    .getByRole("combobox", { name: "모델", exact: true })
    .selectOption("haiku");
  await expect(
    page
      .getByLabel("추론 수준")
      .getByRole("option", { name: "높음", exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("combobox", { name: "모델", exact: true })
    .selectOption("sonnet");
  await expect(page.getByLabel("추론 수준")).toBeEnabled();
  await page.getByLabel("추론 수준").selectOption("high");
  await page.getByRole("button", { name: "저장", exact: true }).click();
  await expect(
    page.getByText("설정을 저장했어요. 다음 분석부터 적용해요."),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("분석 도구")).toHaveValue("claude");
  await expect(
    page.getByRole("combobox", { name: "모델", exact: true }),
  ).toHaveValue("sonnet");
  await expect(page.getByLabel("추론 수준")).toHaveValue("high");
  await page.screenshot({
    path: "test-results/analysis-settings-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByLabel("분석 도구")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/analysis-settings-mobile.png",
    fullPage: true,
  });
});
