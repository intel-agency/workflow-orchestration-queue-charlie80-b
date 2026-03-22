"""Shared HTTPX async client with connection pooling for GitHub API."""

import httpx

from workflow_orchestration_queue.config.settings import get_settings


class GitHubHttpClient:
    """Async HTTP client for GitHub API with connection pooling.

    Provides a reusable HTTP client configured for GitHub API access
    with proper headers, timeouts, and connection pooling.
    """

    def __init__(self) -> None:
        """Initialize the GitHub HTTP client."""
        settings = get_settings()

        self._client = httpx.AsyncClient(
            base_url="https://api.github.com",
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "workflow-orchestration-queue/0.1.0",
                "Authorization": f"Bearer {settings.github_token}",
            },
            timeout=httpx.Timeout(
                connect=10.0,
                read=30.0,
                write=30.0,
                pool=10.0,
            ),
            limits=httpx.Limits(
                max_keepalive_connections=5,
                max_connections=10,
                keepalive_expiry=30.0,
            ),
            http2=True,  # Enable HTTP/2 for better performance
        )

    @property
    def client(self) -> httpx.AsyncClient:
        """Get the underlying HTTPX client."""
        return self._client

    async def close(self) -> None:
        """Close the HTTP client and release connections."""
        await self._client.aclose()

    async def __aenter__(self) -> "GitHubHttpClient":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        """Async context manager exit - close client."""
        await self.close()


# Module-level client singleton (lazy initialized)
_github_client: GitHubHttpClient | None = None


async def get_github_client() -> GitHubHttpClient:
    """Get or create the shared GitHub HTTP client.

    Returns a singleton client instance, creating it on first call.
    """
    global _github_client
    if _github_client is None:
        _github_client = GitHubHttpClient()
    return _github_client


async def close_github_client() -> None:
    """Close the shared GitHub HTTP client if it exists."""
    global _github_client
    if _github_client is not None:
        await _github_client.close()
        _github_client = None
