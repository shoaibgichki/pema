"""
PEMA Application Factory (FastAPI).

Creates and configures the FastAPI application with all routes,
middleware, and lifecycle events.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.admin import router as admin_router
from app.api.sessions import router as sessions_router
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: startup and shutdown."""
    # Startup — import models to ensure they are registered with SQLAlchemy
    import app.models.session  # noqa: F401
    import app.models.message  # noqa: F401
    import app.models.fact  # noqa: F401
    import app.models.rule_event  # noqa: F401
    import app.models.model_audit  # noqa: F401

    yield

    # Shutdown — dispose DB engine
    from app.database import engine

    await engine.dispose()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    application = FastAPI(
        title="PEMA — AI Healthcare Triage",
        description=(
            "AI-powered healthcare triage chatbot that guides patients "
            "in Pakistan to the correct medical specialty."
        ),
        version=settings.engine_version,
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────────────
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Permissive for development; tighten for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ───────────────────────────────────────────────────────
    application.include_router(sessions_router)
    application.include_router(admin_router)

    # ── Static files (sandbox UI) ─────────────────────────────────────
    sandbox_dir = Path(__file__).parent.parent / "sandbox"
    if sandbox_dir.exists():
        application.mount(
            "/sandbox",
            StaticFiles(directory=str(sandbox_dir), html=True),
            name="sandbox",
        )

    # ── Health check ──────────────────────────────────────────────────
    @application.get("/health", tags=["system"])
    async def health_check():
        return {
            "status": "healthy",
            "version": settings.engine_version,
        }

    return application


app = create_app()
