# oh-my-papyrus

## 소개

한국어 대화를 녹음하고 전사·대화 정리·내보내기를 제공하는 로컬 웹 앱이다.
제한된 디바이스에서 음성 인식과 대화 정리의 품질을 개선하고, 결과를 다음 작업에 사용할 수 있게 만드는 것이 목적이다.
정리본을 Markdown 문서로 저장하거나, 전사와 함께 Markdown·JSON으로 내보내 Codex·Claude Code 등에 전달할 수 있다. 보고서·견적서 작성이나 PoC 개발 등 후속 작업은 해당 에이전트에서 진행한다.

## 실행 화면

[![한국어 인터뷰의 전사와 대화 정리 화면](docs/verification/assets/fcseoul-detail.png)](docs/verification/assets/fcseoul-flow.webm)

[데모 영상 보기 · WebM](docs/verification/assets/fcseoul-flow.webm)

2026-10-20 버전에서 처리가 끝난 뒤 촬영한 무음 화면이다. 현재 화면과 일부 차이가 있다.

샘플 출처: **FC SEOUL**, [FC서울 신인 심원성 & 이태석 첫 인터뷰](https://www.youtube.com/watch?v=GnxVJrvGhRE), [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) · [라이선스 기록](https://commons.wikimedia.org/wiki/File:FC서울_신인_심원성_%26_이태석_첫_인터뷰.webm). 원본에서 음성을 추출해 자동 전사·분석한 뒤 앱 화면을 촬영했다.

## 주요 기능

- 브라우저 마이크 녹음과 음성 파일 가져오기
- 음성 처리 단계 안내와 현재 단계의 진행률 표시
- 화자별 전사와 문장 편집, 문장을 눌러 해당 음성 구간 재생
- 일반 회의·요구사항 협의·검토와 결정·진행 점검·사용자 인터뷰 양식으로 대화 정리
- 필요할 때 정리 내용의 근거 발언 확인
- 대화 정리본만 Markdown으로 다운로드
- 전사와 정리 결과를 Markdown·JSON으로 내보내 에이전트에 전달

## 빠른 시작

로컬 음성 모델은 **Apple Silicon Mac**을 대상으로 한다. Python 3.12와 Node.js가 필요하다. Node.js는 22.x의 22.22.2 이상, 24.x의 24.15 이상, 또는 26 이상을 지원한다. 브라우저는 Chrome을 기준으로 확인했다. 최소 메모리 요구량은 아직 확인하지 않았다.

음성 구간 탐지·전사·시간 정렬·화자 구분의 모델 추론은 MLX를 통해 Mac의 GPU를 사용한다. 현재 음성 엔진은 macOS에서 직접 실행하며 Docker 실행 구성은 제공하지 않는다. 웹·API·파일 변환·저장·내보내기에는 모델 추론용 GPU가 필요하지 않다.

### 1. 설치

Homebrew를 사용하는 경우 아래 명령을 실행한다.

```bash
git clone https://github.com/YongGyun-Kim/oh-my-papyrus.git
cd oh-my-papyrus
brew install uv node ffmpeg
bash scripts/setup.sh
```

설치 스크립트는 실행 환경과 필수 도구를 확인하고, 고정된 의존성 설치·음성 모델 다운로드·설치 진단을 순서대로 실행한다. 중간에 실패하면 해당 단계에서 멈춘다. Ollama와 대화 분석용 CLI는 별도로 설치한다.

### 2. 음성 모델 다운로드

| 용도           | 모델                                                                                                  |
| -------------- | ----------------------------------------------------------------------------------------------------- |
| 음성 구간 탐지 | [Silero VAD](https://huggingface.co/mlx-community/silero-vad)                                         |
| 전사           | [Qwen3-ASR 1.7B · 8bit](https://huggingface.co/mlx-community/Qwen3-ASR-1.7B-8bit)                     |
| 발언 시간 정렬 | [Qwen3 ForcedAligner 0.6B · 8bit](https://huggingface.co/mlx-community/Qwen3-ForcedAligner-0.6B-8bit) |
| 화자 구분      | [Nemotron 3 Diarization](https://huggingface.co/mlx-community/Nemotron-3-Diarization)                 |

설치 스크립트가 표의 모델을 준비한다. **설정 → 모델 준비 상태**에서도 모델을 다운로드하거나 다시 받을 수 있다. 진행률은 완료한 파일 수를 기준으로 표시하며, 실패하면 원인 안내를 확인하고 다시 시도한다. 전사·분석 중에는 모델 다운로드가 대기한다. 시간 정렬 모델은 문장별 재생 위치와 화자 연결에 사용한다.

터미널에서 모델 준비만 다시 실행하려면 아래 명령을 사용한다.

```bash
uv run --no-sync meetinglog prepare-models
```

최초 다운로드에는 인터넷 연결과 수 GB 이상의 저장 공간이 필요하다.

### 3. 대화 분석

음성 전사와 별도로 Codex·Claude Code를 사용하거나, Ollama로 로컬 모델을 실행해 대화를 분석할 수 있다.

Ollama는 서버 컴퓨터에서 모델을 실행하며 GPU를 활용할 수 있다. Codex·Claude Code의 계정 연결이나 OpenAI API를 사용하면 모델 추론은 제공사 서버에서 수행한다.

| 방식                                                                                                     | 사용 방법                                                                                                         |
| -------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| [Codex](https://learn.chatgpt.com/docs/codex/cli) · [Claude Code](https://code.claude.com/docs/en/setup) | 서버에 설치하고 로그인한 CLI로 앱에서 대화를 분석한다. MCP는 연결하지 않는다. |
| 로컬 모델                                                                                                | Ollama를 통해 앱에서 대화 분석을 실행한다. 기본 모델은 [gpt-oss:20b](https://ollama.com/library/gpt-oss)다.       |

**설정 → 대화 분석 모델**에서 도구·모델·추론 수준을 저장한다. Codex·Claude Code는 **계정 연결**에서 로그인한다. 연결된 CLI에서 모델 목록과 모델별 추론 수준을 조회한다. 조회하지 못하면 직접 입력과 기본 추론만 사용할 수 있다. 설정은 다음 분석부터 적용되며 전사 방식은 바뀌지 않는다. 기존 OpenAI API도 서버의 API 키로 사용할 수 있다.

로컬에서 분석하려면 [Ollama를 다운로드](https://ollama.com/download)하거나 Homebrew로 설치한다.

```bash
brew install ollama
```

Ollama 앱이나 서버를 실행한다. 실행 중인 서버가 없다면 별도 터미널에서 시작한다.

```bash
ollama serve
```

다른 터미널에서 분석 모델을 다운로드한다.

```bash
ollama pull gpt-oss:20b
```

### 4. 실행

```bash
bash scripts/dev.sh
```

[http://127.0.0.1:5173](http://127.0.0.1:5173)을 연다. 웹·API·워커가 함께 실행된다. **설정 → 실행 준비 상태**에서 워커·FFmpeg·선택한 분석 도구의 상태를, **모델 준비 상태**에서 음성 모델을 확인한다. 분석 도구의 인증·설정 확인은 실제 모델 호출의 성공 여부와 구분한다.

녹음하거나 파일을 가져온 뒤 전사를 확인한다. 분석 도구를 설정한 뒤 **대화 정리**에서 양식을 고르고 **정리 시작**을 눌러 분석한다. 양식 선택만으로 분석하지 않으며, 다른 양식으로 다시 정리하면 새 결과를 저장한다.

휴대폰에서는 기본 녹음 앱으로 녹음한다. 저장한 파일을 서버 PC로 옮긴 뒤 **파일 가져오기**에서 업로드한다. M4A·MP3·WAV·WebM 등을 받을 수 있으며, 파일당 최대 2시간·2GB(2,000,000,000바이트)다. 휴대폰 브라우저의 마이크 녹음과 서버 직접 접속은 지원 범위에 포함하지 않는다.

현재는 서버 컴퓨터에서 접속하는 로컬 실행을 기준으로 한다. 원본 음성·전사·정리 결과는 `data/`, 음성 모델은 `models/`에 저장하며 두 경로는 Git에서 제외한다.

종료는 `Ctrl+C`로 한다. 코드를 업데이트한 뒤에는 다시 실행한다. 별도로 실행한 Ollama는 따로 종료한다.

### 5. 내보내기

기록 상세 화면에서 **내보내기**를 누른다.

| 메뉴 | 포함 내용과 용도 |
| --- | --- |
| 대화 정리 · Markdown | 제목, 정리 내용, 비교표, 할 일·담당자·기한을 담은 정리본. 전사 원문과 근거 ID는 제외한다. |
| Markdown · 에이전트 전달용 | 현재 전사와 해당 전사를 기준으로 만든 정리 결과, 근거 ID와 버전 정보. 후속 작업에 참고할 문서다. |
| JSON · AI 분석용 | 현재 전사, 해당 전사 기준의 정리 결과와 처리 이력을 담은 구조화 데이터. 다른 도구나 에이전트에서 재사용한다. |

**대화 정리 · Markdown**은 정리가 끝나면 사용할 수 있다. 화면에 표시된 정리본을 추가 분석 없이 다운로드한다. 전사를 수정한 뒤 다시 정리하지 않았다면 수정 전 정리본이 내보내진다.
