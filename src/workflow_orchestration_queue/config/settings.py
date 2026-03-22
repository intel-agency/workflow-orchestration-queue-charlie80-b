"""Pydantic Settings configuration with environment variable validation."""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Required environment variables
    github_token: str = Field(
        ...,
        description="GitHub API authentication token",
    )
    github_repo: str = Field(
        ...,
        description="Target repository in owner/repo format",
    )
    sentinel_bot_login: str = Field(
        ...,
        description="Bot account login for task claiming",
    )

    # Optional configuration with defaults
    poll_interval: int = Field(
        default=60,
        ge=1,
        description="Polling interval in seconds",
    )
    max_backoff: int = Field(
        default=960,
        ge=1,
        description="Maximum backoff for rate limiting in seconds",
    )
    heartbeat_interval: int = Field(
        default=300,
        ge=60,
        description="Heartbeat comment interval in seconds",
    )
    subprocess_timeout: int = Field(
        default=5700,
        ge=60,
        description="Maximum task execution time in seconds",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level",
    )
    environment: str = Field(
        default="development",
        description="Environment name (development, staging, production)",
    )

    @field_validator("github_token", "github_repo", "sentinel_bot_login")
    @classmethod
    def reject_placeholders(cls, v: str) -> str:
        """Reject placeholder values that indicate unconfigured settings."""
        placeholders = [
            "your-token-here",
            "your_token_here",
            "your-repo-here",
            "your_repo_here",
            "your-bot-here",
            "your_bot_here",
            "<token>",
            "<repo>",
            "<bot>",
            "changeme",
            "placeholder",
        ]
        v_lower = v.lower().strip()
        for placeholder in placeholders:
            if placeholder in v_lower:
                raise ValueError(
                    f"Placeholder value '{placeholder}' detected. Please configure a real value."
                )
        return v

    @field_validator("github_repo")
    @classmethod
    def validate_repo_format(cls, v: str) -> str:
        """Validate repository is in owner/repo format."""
        if "/" not in v:
            raise ValueError(f"Repository '{v}' must be in 'owner/repo' format")
        parts = v.split("/")
        if len(parts) != 2 or not all(parts):
            raise ValueError(f"Repository '{v}' must be in 'owner/repo' format")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is a valid Python logging level."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"Log level '{v}' must be one of: {', '.join(valid_levels)}")
        return v_upper

    def validate_settings(self) -> None:
        """Explicit validation method that can be called at startup.

        This triggers all validators and raises an exception if any
        configuration is invalid.
        """
        # Access all required fields to trigger validation
        _ = self.github_token
        _ = self.github_repo
        _ = self.sentinel_bot_login


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    Uses LRU cache to ensure settings are only loaded once.
    """
    return Settings()  # type: ignore[call-arg]
