import { render } from "@testing-library/react";
import { vi } from "vitest";
import type { RecordingDetail as Detail } from "../lib/types";
import { api } from "../lib/api";
import { RecordingDetail } from "../features/detail/RecordingDetail";

export const detailFixture: Detail = {
  recording: {
    id: "rec-1",
    title: "서비스 인터뷰",
    source: "file",
    input_state: "ready",
    duration_ms: 9000,
    generation: 0,
  },
  transcript: {
    id: "v1",
    recording_id: "rec-1",
    speakers: [{ id: "a", display_name: "화자 A", role: null }],
    turns: [
      {
        id: "turn:t1",
        speaker_id: "a",
        sentences: [
          {
            id: "t1",
            start_ms: 1250,
            end_ms: 4000,
            text_original: "다음 주에 시작합니다.",
            review_flags: [],
          },
        ],
      },
    ],
  },
  analysis: {
    id: "analysis-1",
    transcript_id: "v1",
    provider: "local",
    model: "test",
    prompt_version: "v1",
    form: "meeting",
    body: {
      overview: {
        kind: "interview",
        summary: {
          text: "시작 시점을 이야기했습니다.",
          evidence_sentence_ids: ["t1"],
        },
        main_topics: [],
      },
      topics: [],
      question_answers: [],
      agreements: [],
      open_questions: [],
      actions: [],
    },
  },
  analysis_stale: false,
  processing_history: [],
  job: null,
};

export function renderDetailWithFixture(
  detail: Detail = structuredClone(detailFixture),
) {
  vi.spyOn(api, "detail").mockResolvedValue(detail);
  vi.spyOn(api, "forms").mockResolvedValue([
    {
      id: "meeting",
      title: "일반 회의",
      description: "회의 내용 정리",
      sections: ["회의 결과", "안건별 논의", "후속 조치", "남은 쟁점"],
    },
    {
      id: "interview",
      title: "사용자 인터뷰",
      description: "경험 정리",
      sections: ["사용자 상황", "경험과 문제"],
    },
    {
      id: "project",
      title: "요구사항 협의",
      description: "요구사항 정리",
      sections: ["목표", "요구사항", "예산", "일정"],
    },
    {
      id: "decision",
      title: "검토와 결정",
      description: "선택지와 결정 정리",
      sections: ["결정 결과", "판단 기준", "선택지 비교"],
    },
    {
      id: "progress",
      title: "진행 점검",
      description: "진행 상태 정리",
      sections: ["현재 상태", "완료한 일", "다음 할 일"],
    },
  ]);
  vi.spyOn(api, "settings").mockResolvedValue({
    mode: "local_only",
    engines: [],
    api_configured: false,
    media_tools_ready: true,
    worker_running: true,
  });
  const view = render(
    <RecordingDetail id="rec-1" onBack={() => {}} onDeleted={() => {}} />,
  );
  return view;
}
