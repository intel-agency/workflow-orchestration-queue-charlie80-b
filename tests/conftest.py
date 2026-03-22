"""Shared pytest fixtures for workflow orchestration queue tests."""

import os
from collections.abc import AsyncIterator, Generator
from unittest.mock import AsyncMock

import pytest

from workflow_orchestration_queue.config.settings import Settings


@pytest.fixture
def mock_env_vars() -> Generator[None, None, None]:
    """Set up mock environment variables for testing."""
    original_env = os.environ.copy()

    os.environ.update(
        {
            "GITHUB_TOKEN": "ghp_test_token_for_testing_12345",
            "GITHUB_REPO": "test-owner/test-repo",
            "SENTINEL_BOT_LOGIN": "test-bot",
        }
    )

    yield

    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)


@pytest.fixture
def settings(mock_env_vars: None) -> Settings:
    """Create a Settings instance with test defaults."""
    # Clear the LRU cache to pick up new env vars
    from workflow_orchestration_queue.config.settings import get_settings

    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
async def mock_http_client() -> AsyncIterator[AsyncMock]:
    """Create a mock HTTP client for testing."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock()
    mock_client.post = AsyncMock()
    mock_client.put = AsyncMock()
    mock_client.patch = AsyncMock()
    mock_client.delete = AsyncMock()
    mock_client.aclose = AsyncMock()
    yield mock_client


@pytest.fixture
def app():
    """Create a FastAPI app instance for testing."""
    from workflow_orchestration_queue.app import create_app

    return create_app()
