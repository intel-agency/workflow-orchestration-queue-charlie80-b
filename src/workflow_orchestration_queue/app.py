"""FastAPI application factory with health check endpoints."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from workflow_orchestration_queue.config.settings import get_settings


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan manager for startup/shutdown events."""
    settings = get_settings()
    # Validate settings on startup
    settings.validate_settings()
    yield


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()  # noqa: F841 - Available for future configuration

    app = FastAPI(
        title="Workflow Orchestration Queue",
        description="GitHub Actions-based AI orchestration system for workflow automation",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Configure CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routes
    register_routes(app)

    return app


def register_routes(app: FastAPI) -> None:
    """Register all application routes."""

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        """Basic health check endpoint."""
        return {"status": "healthy"}

    @app.get("/ready")
    async def readiness_check() -> dict[str, Any]:
        """Readiness check endpoint - validates configuration."""
        settings = get_settings()
        try:
            settings.validate_settings()
            return {"status": "ready", "environment": settings.environment}
        except Exception as e:
            return {"status": "not ready", "error": str(e)}


# Create default app instance for ASGI servers
app = create_app()
