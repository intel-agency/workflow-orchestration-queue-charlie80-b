"""Notifier service for handling webhook notifications and event processing."""

import logging

import uvicorn

from workflow_orchestration_queue.config.settings import get_settings

logger = logging.getLogger(__name__)


def run() -> None:
    """Run the notifier service with Uvicorn ASGI server."""
    settings = get_settings()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info(f"Starting notifier service in {settings.environment} environment")

    # Run with Uvicorn
    uvicorn.run(
        "workflow_orchestration_queue.app:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.environment == "development",
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()
