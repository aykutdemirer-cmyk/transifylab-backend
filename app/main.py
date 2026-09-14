"""FastAPI application entrypoint."""
from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import get_settings
from app.routers import convert, files, transcribe
from app.schemas import HealthResponse
from app.services.cleanup import cleanup_loop
from app.services.storage import store
from app.uploads import MaxBodySizeMiddleware

logging.basicConfig(
    level=get_settings().log_level.upper(),
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
logger = logging.getLogger("app")


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.temp_path.mkdir(parents=True, exist_ok=True)
    store.reconcile_disk()

    stop_event = asyncio.Event()
    task = asyncio.create_task(cleanup_loop(stop_event), name="cleanup-loop")
    logger.info("%s v%s started (env=%s)", settings.app_name, __version__, settings.environment)
    try:
        yield
    finally:
        stop_event.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        store.clear_all()
        logger.info("shutdown complete; temp files cleared")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
        description="Document conversion (PDF↔Word, Text→PDF) and speech-to-text.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )
    app.add_middleware(MaxBodySizeMiddleware, max_bytes=settings.max_upload_size_bytes)

    app.include_router(convert.router)
    app.include_router(transcribe.router)
    app.include_router(files.router)

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {"service": settings.app_name, "version": __version__, "docs": "/docs"}

    @app.get("/api/v1/health", response_model=HealthResponse, tags=["health"])
    def health() -> HealthResponse:
        return HealthResponse(
            app=settings.app_name,
            version=__version__,
            transcription_backend=settings.transcription_backend,
            features={
                "pdf_to_word": _module_available("pdf2docx"),
                "docx_to_pdf": _module_available("docx") or bool(settings.soffice_bin),
                "text_to_pdf": _module_available("reportlab"),
                "faster_whisper": _module_available("faster_whisper"),
                "openai_whisper": _module_available("openai") and bool(settings.openai_api_key),
                "diarization": _module_available("sherpa_onnx") and settings.diarization_available,
            },
        )

    return app


app = create_app()
