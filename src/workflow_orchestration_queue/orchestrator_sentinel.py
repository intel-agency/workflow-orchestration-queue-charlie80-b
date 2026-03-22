"""Orchestrator sentinel for polling and coordinating workflow execution."""

import asyncio
import logging
import signal
import sys
from typing import Any

from workflow_orchestration_queue.config.settings import get_settings
from workflow_orchestration_queue.queue import get_github_client

logger = logging.getLogger(__name__)

# Global shutdown flag
_shutdown_requested = False


def _signal_handler(signum: int, _frame: Any) -> None:
    """Handle shutdown signals gracefully."""
    global _shutdown_requested
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    _shutdown_requested = True


async def main() -> None:
    """Main sentinel loop for polling and task coordination."""
    global _shutdown_requested

    settings = get_settings()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info(f"Starting sentinel service in {settings.environment} environment")
    logger.info(f"Monitoring repository: {settings.github_repo}")
    logger.info(f"Bot login: {settings.sentinel_bot_login}")
    logger.info(f"Poll interval: {settings.poll_interval}s")

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    try:
        _client = await get_github_client()

        while not _shutdown_requested:
            try:
                logger.debug("Polling for tasks...")
                # TODO: Implement task polling logic in future stories
                # This is a placeholder that just waits
                await asyncio.sleep(settings.poll_interval)

            except asyncio.CancelledError:
                logger.info("Polling cancelled")
                break
            except Exception as e:
                logger.error(f"Error during polling: {e}", exc_info=True)
                # Back off on error
                await asyncio.sleep(min(settings.poll_interval * 2, settings.max_backoff))

    finally:
        logger.info("Shutting down sentinel service...")


def run() -> None:
    """Run the sentinel service."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Sentinel stopped by user")
        sys.exit(0)


if __name__ == "__main__":
    run()
