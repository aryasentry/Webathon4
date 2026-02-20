"""
UGIE — Universal GitHub Intelligence Engine
FastAPI Application Factory
────────────────────────────────────────────
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.utils.logging import configure_logging, get_logger, new_correlation_id

# Configure JSON logging before anything else
configure_logging()
logger = get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and teardown."""
    logger.info(
        "UGIE starting",
        extra={
            "service": settings.api_title,
            "version": settings.api_version,
            "environment": settings.environment,
        },
    )
    
    from app.workers.scheduler import run_periodic_sync
    sync_task = asyncio.create_task(run_periodic_sync())
    
    yield
    
    sync_task.cancel()
    try:
        await sync_task
    except asyncio.CancelledError:
        pass
        
    logger.info("UGIE shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        description=(
            "Universal GitHub Intelligence Engine — "
            "production-grade developer telemetry infrastructure and team intelligence pipeline."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ── CORS ─────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Correlation-ID middleware ─────────────────────────────────────────────
    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next):
        cid = request.headers.get("X-Correlation-ID") or new_correlation_id()
        request.state.correlation_id = cid
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = cid
        return response

    # ── Global exception handler ──────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(
            "Unhandled exception",
            extra={
                "path": request.url.path,
                "method": request.method,
                "error": str(exc),
                "cid": getattr(request.state, "correlation_id", "none"),
            },
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "type": type(exc).__name__},
        )

    # ── Routers ───────────────────────────────────────────────────────────────
    from app.routers import analytics, auth, health, repos, webhooks, collaboration, ai, tasks, codepolice

    app.include_router(health.router)          # /health/live, /health/ready, /metrics
    app.include_router(auth.router)            # /auth/*
    app.include_router(repos.router)           # /repos/*
    app.include_router(webhooks.router)        # /webhooks/github
    app.include_router(analytics.router)       # /analytics/*
    app.include_router(collaboration.router)   # /repos/{repo_id}/collaboration/*
    app.include_router(ai.router)              # /ai/*
    app.include_router(tasks.router)           # /tasks/*
    app.include_router(codepolice.router)      # /codepolice/*

    logger.info("All routers registered")
    return app


# Module-level app instance (used by uvicorn)
app = create_app()
