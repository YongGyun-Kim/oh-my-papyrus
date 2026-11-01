#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  printf '로컬 음성 모델 설치는 Apple Silicon Mac을 지원해요. arm64 터미널에서 실행해 주세요.\n' >&2
  exit 1
fi

missing=()
for tool in uv node npm ffmpeg ffprobe; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    missing+=("$tool")
  fi
done
if (( ${#missing[@]} )); then
  printf '필요한 도구가 없어요: %s\n' "${missing[*]}" >&2
  printf 'Homebrew를 사용한다면 brew install uv node ffmpeg를 실행해 주세요.\n' >&2
  exit 1
fi
if ! node -e '
  const [major, minor, patch] = process.versions.node.split(".").map(Number);
  const supported = major >= 26
    || (major === 24 && minor >= 15)
    || (major === 22 && (minor > 22 || (minor === 22 && patch >= 2)));
  process.exit(supported ? 0 : 1);
'; then
  printf 'Node.js 22.22.2 이상의 22.x, 24.15 이상의 24.x 또는 26 이상을 설치해 주세요.\n' >&2
  exit 1
fi

printf 'Python 의존성을 설치해요.\n'
uv sync --frozen --extra speech
printf '웹 의존성을 설치해요.\n'
npm --prefix web ci
printf '음성 모델을 준비해요. 최초 다운로드에는 수 GB의 저장 공간이 필요해요.\n'
uv run --no-sync meetinglog prepare-models
printf '설치 상태를 확인해요. 대화 분석 도구는 웹 설정에서 선택할 수 있어요.\n'
uv run --no-sync meetinglog doctor
printf '설치가 끝났어요. bash scripts/dev.sh로 실행해 주세요.\n'
