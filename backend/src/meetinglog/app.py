from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from meetinglog.cli_auth import CliAuth
from meetinglog.config import Settings
from meetinglog.db import ApiError, Database
from meetinglog.model_preparation import ModelPreparation


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    db = Database(settings.database_path)
    cli_auth = CliAuth()
    model_preparation = ModelPreparation(settings)

    @asynccontextmanager
    async def lifespan(app):
        db.migrate()
        try:
            yield
        finally:
            model_preparation.close()
            cli_auth.close()

    app = FastAPI(title="Meetinglog", version="0.1.0", lifespan=lifespan)
    app.state.settings, app.state.db = settings, db
    app.state.cli_auth = cli_auth
    app.state.model_preparation = model_preparation
    from meetinglog.recordings.api import router as input_router

    app.include_router(input_router)
    from meetinglog.transcripts.api import router as transcript_router

    app.include_router(transcript_router)
    from meetinglog.jobs.api import router as job_router

    app.include_router(job_router)
    from meetinglog.settings_api import router as settings_router

    app.include_router(settings_router)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def loopback_boundary(request: Request, call_next):
        if request.url.hostname not in ("localhost", "127.0.0.1", "::1"):
            return JSONResponse(
                {
                    "error": {
                        "code": "invalid_host",
                        "message": "로컬 주소로 접속하세요",
                        "retryable": False,
                    }
                },
                status_code=400,
            )
        origin = request.headers.get("origin")
        if origin is not None and origin not in settings.allowed_origins:
            return JSONResponse(
                {
                    "error": {
                        "code": "invalid_origin",
                        "message": "허용되지 않은 웹 주소입니다",
                        "retryable": False,
                    }
                },
                status_code=403,
            )
        return await call_next(request)

    @app.exception_handler(ApiError)
    async def api_error(request, error: ApiError):
        return JSONResponse(
            {"error": {"code": error.code, "message": error.message, "retryable": error.retryable}},
            status_code=error.status,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return JSONResponse(
            {
                "error": {
                    "code": "invalid_input",
                    "message": "입력 항목을 확인하세요",
                    "retryable": False,
                }
            },
            status_code=422,
        )

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    return app
