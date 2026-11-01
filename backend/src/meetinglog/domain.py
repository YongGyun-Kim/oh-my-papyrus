from datetime import UTC, datetime
from typing import Literal, Self
from uuid import uuid4

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

Mode = Literal["auto", "local_only", "api"]
AnalysisForm = Literal["meeting", "interview", "project", "decision", "progress"]
SpeechModel = Literal["vad", "asr", "aligner", "diarizer"]


def now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalysisSettings(Contract):
    provider: Literal["ollama", "codex", "claude", "openai"]
    model: str = Field(max_length=128, pattern=r"^$|^[a-zA-Z0-9][a-zA-Z0-9._:/\[\]-]*$")
    reasoning: str = Field(default="default", max_length=32, pattern=r"^[a-z][a-z0-9_-]*$")

    @model_validator(mode="after")
    def supported_reasoning(self) -> Self:
        levels = {
            "ollama": {"default", "off", "on", "low", "medium", "high"},
            "openai": {"default", "none", "minimal", "low", "medium", "high", "xhigh"},
        }
        if self.provider in levels and self.reasoning not in levels[self.provider]:
            raise ValueError("지원하지 않는 추론 수준")
        if self.provider in ("ollama", "openai") and not self.model:
            raise ValueError("모델 이름이 필요합니다")
        if self.provider == "ollama" and self.model.split(":")[0] == "gpt-oss":
            if self.reasoning in ("off", "on"):
                raise ValueError("gpt-oss는 low, medium, high를 사용합니다")
        return self


class Recording(Contract):
    id: str
    title: str
    source: Literal["microphone", "file"]
    input_state: Literal["recording", "uploading", "ready", "invalid"]
    duration_ms: int | None = None
    created_at: datetime = Field(default_factory=now)
    generation: int = 0


class Word(Contract):
    text: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    review_flags: list[str] | None = None


class Sentence(Contract):
    id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    text_original: str = Field(min_length=1)
    text_edited: str | None = None
    review_flags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_time(self) -> Self:
        if self.end_ms <= self.start_ms or not self.text_original.strip():
            raise ValueError("발언의 시간과 원문을 확인하세요")
        return self


class SpeechSegment(Sentence):
    speaker_id: str | None = None
    words: list[Word] = Field(default_factory=list)


class Turn(Contract):
    id: str
    speaker_id: str | None = None
    sentences: list[Sentence] = Field(min_length=1)


def group_sentences(entries: list[tuple[str | None, Sentence]]) -> list[Turn]:
    turns = []
    for speaker_id, sentence in entries:
        if speaker_id is not None and turns and turns[-1].speaker_id == speaker_id:
            turns[-1].sentences.append(sentence)
        else:
            turns.append(
                Turn(id=f"turn:{sentence.id}", speaker_id=speaker_id, sentences=[sentence])
            )
    return turns


class Speaker(Contract):
    id: str
    display_name: str
    role: str | None = None


class Transcript(Contract):
    id: str
    recording_id: str
    parent_id: str | None = None
    turns: list[Turn]
    speakers: list[Speaker]
    created_at: datetime = Field(default_factory=now)

    @model_validator(mode="before")
    @classmethod
    def read_legacy(cls, value):
        if (
            isinstance(value, dict)
            and value.get("turns")
            and all(
                isinstance(turn, SpeechSegment)
                or isinstance(turn, dict)
                and "sentences" not in turn
                for turn in value["turns"]
            )
        ):
            entries = []
            for item in value["turns"]:
                segment = SpeechSegment.model_validate(item)
                sentence = Sentence.model_validate(
                    segment.model_dump(exclude={"speaker_id", "words"})
                )
                entries.append((segment.speaker_id, sentence))
            return {**value, "turns": group_sentences(entries)}
        return value

    def entries(self) -> list[tuple[str | None, Sentence]]:
        return [(turn.speaker_id, sentence) for turn in self.turns for sentence in turn.sentences]

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        if len({turn.id for turn in self.turns}) != len(self.turns):
            raise ValueError("발언 ID가 중복되었습니다")
        if len({speaker.id for speaker in self.speakers}) != len(self.speakers):
            raise ValueError("화자 ID가 중복되었습니다")
        sentences = [sentence for _, sentence in self.entries()]
        if len({sentence.id for sentence in sentences}) != len(sentences):
            raise ValueError("문장 ID가 중복되었습니다")
        return self


class Fact(Contract):
    text: str
    evidence_sentence_ids: list[str] = Field(
        min_length=1, validation_alias=AliasChoices("evidence_sentence_ids", "evidence_turn_ids")
    )


class Overview(Contract):
    kind: Literal["interview", "counseling", "conversation", "unknown"]
    summary: Fact
    main_topics: list[Fact]


class Topic(Contract):
    title: str
    discussion: list[Fact]
    different_views: list[Fact]
    conclusion: Fact | None
    evidence_sentence_ids: list[str] = Field(
        min_length=1, validation_alias=AliasChoices("evidence_sentence_ids", "evidence_turn_ids")
    )

    @model_validator(mode="before")
    @classmethod
    def read_legacy_times(cls, value):
        if isinstance(value, dict):
            return {key: item for key, item in value.items() if key not in ("start_ms", "end_ms")}
        return value


class QuestionAnswer(Contract):
    question: Fact
    answer: Fact | None


class Action(Contract):
    text: str
    owner_speaker_id: str | None
    due_text: str | None
    evidence_sentence_ids: list[str] = Field(
        min_length=1, validation_alias=AliasChoices("evidence_sentence_ids", "evidence_turn_ids")
    )


class AnalysisBody(Contract):
    overview: Overview
    topics: list[Topic]
    question_answers: list[QuestionAnswer]
    agreements: list[Fact]
    open_questions: list[Fact]
    actions: list[Action]


class ParagraphGroup(Contract):
    title: str | None
    paragraphs: list[Fact] = Field(min_length=1)


class OptionComparison(Contract):
    option: str = Field(min_length=1)
    points: list[Fact] = Field(min_length=1)


class FormAction(Action):
    owner_text: str | None = None


class AnalysisSection(Contract):
    title: str = Field(min_length=1)
    groups: list[ParagraphGroup] = Field(default_factory=list)
    comparisons: list[OptionComparison] = Field(default_factory=list)
    actions: list[FormAction] = Field(default_factory=list)


class FormAnalysisBody(Contract):
    sections: list[AnalysisSection]

    @property
    def actions(self) -> list[FormAction]:
        return [action for section in self.sections for action in section.actions]


class AnalysisVersion(Contract):
    id: str
    transcript_id: str
    body: FormAnalysisBody | AnalysisBody
    provider: str
    model: str
    prompt_version: str
    reasoning: str | None = None
    form: AnalysisForm = "meeting"
    created_at: datetime = Field(default_factory=now)


class Job(Contract):
    id: str
    recording_id: str
    transcript_id: str | None = None
    kind: Literal["process", "analyze"]
    state: str
    stage: str
    generation: int
    mode: Mode
    form: AnalysisForm = "meeting"
    created_at: datetime = Field(default_factory=now)
    error_code: str | None = None
    error_message: str | None = None


class SpeechResult(Contract):
    turns: list[SpeechSegment]
    speakers: list[Speaker]
    no_speech: bool = False
    provider: str
    model: str
    raw_artifact: str = ""


class StageRequest(Contract):
    job_id: str
    recording_id: str
    generation: int
    stage: str
    input_path: str
    output_path: str
    mode: Mode
    form: AnalysisForm = "meeting"
    analysis_settings: AnalysisSettings | None = None
    model_name: SpeechModel | None = None


class StageResult(Contract):
    job_id: str
    generation: int
    stage: str
    artifact_path: str
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
