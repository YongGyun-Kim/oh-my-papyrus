import json
import shutil
from typing import Literal

import httpx
from fastapi import APIRouter, Request

from meetinglog.analysis.settings import (
    AnalysisOptions,
    analysis_settings,
    options,
    validate_selection,
)
from meetinglog.cli_auth import CliAuth, CliConnection, CliProvider
from meetinglog.config import Settings
from meetinglog.db import ApiError, Database
from meetinglog.domain import AnalysisSettings, Contract, Mode, SpeechModel
from meetinglog.engines.models import ModelRegistry
from meetinglog.engines.policy import loopback_url
from meetinglog.jobs.locks import worker_running
from meetinglog.model_preparation import ModelDownload

router = APIRouter(prefix="/api/settings", tags=["settings"])


class EngineReadiness(Contract):
    name: str
    repo_id: str
    ready: bool
    revision: str | None = None
    quality: str = "unverified"


class AnalysisConnection(Contract):
    provider: Literal["ollama", "codex", "claude", "openai"]
    model: str
    ready: bool
    status: str


class Readiness(Contract):
    mode: Mode
    engines: list[EngineReadiness]
    api_configured: bool
    media_tools_ready: bool
    worker_running: bool = False
    analysis_connection: AnalysisConnection | None = None


class ModeInput(Contract):
    mode: Mode


class CliLoginInput(Contract):
    pass


@router.get("/analysis", response_model=AnalysisSettings)
def get_analysis_settings(request: Request):
    return analysis_settings(request.app.state.db, request.app.state.settings)


@router.patch("/analysis", response_model=AnalysisSettings)
def update_analysis_settings(request: Request, body: AnalysisSettings):
    body = validate_selection(body, request.app.state.settings)
    with request.app.state.db.session(immediate=True) as connection:
        connection.execute(
            "INSERT INTO settings(key,value) VALUES('analysis',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (body.model_dump_json(),),
        )
    return body


@router.get("/analysis/options", response_model=AnalysisOptions)
def analysis_options(
    request: Request, provider: CliProvider | Literal["ollama", "openai"], model: str = ""
):
    return options(provider, model, request.app.state.settings)


def effective_mode(db: Database, settings: Settings) -> Mode:
    with db.session() as connection:
        row = connection.execute("SELECT value FROM settings WHERE key='mode'").fetchone()
        return ModeInput(mode=json.loads(row[0])).mode if row else settings.mode


def readiness(db: Database, settings: Settings, cli_auth: CliAuth | None = None) -> Readiness:
    selected = analysis_settings(db, settings)
    if selected.provider == "ollama":
        settings = settings.model_copy(update={"ollama_model": selected.model})
    engines = [EngineReadiness(**item) for item in ModelRegistry(settings).readiness()]
    available, digest, connected = False, None, False
    if selected.provider == "ollama":
        try:
            with httpx.Client(
                base_url=loopback_url(settings.ollama_url),
                timeout=1,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = client.get("/api/tags")
                response.raise_for_status()
                connected = True
                item = next(
                    (
                        item
                        for item in response.json().get("models", [])
                        if item.get("name") == settings.ollama_model
                    ),
                    None,
                )
                available, digest = item is not None, item.get("digest") if item else None
        except (ApiError, httpx.HTTPError, ValueError, TypeError, AttributeError):
            pass
        engines.append(
            EngineReadiness(
                name="analysis", repo_id=settings.ollama_model, ready=available, revision=digest
            )
        )
        connection = AnalysisConnection(
            provider="ollama",
            model=selected.model,
            ready=available,
            status="모델 준비됨"
            if available
            else "모델 준비 필요"
            if connected
            else "Ollama 실행 필요",
        )
    elif selected.provider in ("codex", "claude"):
        auth = (cli_auth or CliAuth()).status(selected.provider)
        labels = {
            "connected": "로그인됨",
            "logged_out": "로그인 필요",
            "not_installed": "설치 필요",
            "logging_in": "로그인 대기 중",
            "error": "확인 필요",
        }
        connection = AnalysisConnection(
            provider=selected.provider,
            model=selected.model,
            ready=auth.state == "connected",
            status=labels[auth.state],
        )
    else:
        connection = AnalysisConnection(
            provider="openai",
            model=selected.model,
            ready=bool(settings.openai_api_key),
            status="API 키 설정됨" if settings.openai_api_key else "API 키 설정 필요",
        )
    return Readiness(
        mode=effective_mode(db, settings),
        engines=engines,
        api_configured=bool(settings.openai_api_key),
        media_tools_ready=bool(shutil.which("ffmpeg") and shutil.which("ffprobe")),
        worker_running=worker_running(settings),
        analysis_connection=connection,
    )


@router.get("", response_model=Readiness)
def get(request: Request):
    return readiness(request.app.state.db, request.app.state.settings, request.app.state.cli_auth)


@router.patch("", response_model=Readiness)
def update(request: Request, body: ModeInput):
    with request.app.state.db.session(immediate=True) as connection:
        connection.execute(
            "INSERT INTO settings(key,value) VALUES('mode',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps(body.mode),),
        )
    return readiness(request.app.state.db, request.app.state.settings, request.app.state.cli_auth)


@router.get("/models/download", response_model=ModelDownload)
def model_download(request: Request):
    return request.app.state.model_preparation.status()


@router.post("/models/{model}/download", response_model=ModelDownload)
def prepare_model(model: SpeechModel, body: CliLoginInput, request: Request):
    if request.headers.get("origin") not in request.app.state.settings.allowed_origins:
        raise ApiError("invalid_origin", "설정 화면에서 모델 다운로드를 시작해 주세요.", 403)
    return request.app.state.model_preparation.start(model)


@router.get("/cli-connections", response_model=list[CliConnection])
def cli_connections(request: Request):
    return request.app.state.cli_auth.connections()


@router.post("/cli-connections/{provider}/login", response_model=CliConnection)
def cli_login(provider: CliProvider, body: CliLoginInput, request: Request):
    if request.headers.get("origin") not in request.app.state.settings.allowed_origins:
        raise ApiError("invalid_origin", "설정 화면에서 로그인을 시작해 주세요.", status=403)
    return request.app.state.cli_auth.start(provider)


@router.post("/cli-connections/{provider}/cancel", response_model=CliConnection)
def cancel_cli_login(provider: CliProvider, body: CliLoginInput, request: Request):
    if request.headers.get("origin") not in request.app.state.settings.allowed_origins:
        raise ApiError("invalid_origin", "설정 화면에서 로그인을 취소해 주세요.", status=403)
    return request.app.state.cli_auth.cancel(provider)
