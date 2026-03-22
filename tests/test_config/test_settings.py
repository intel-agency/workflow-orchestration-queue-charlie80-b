"""Tests for Pydantic Settings configuration."""

import os

import pytest
from pydantic import ValidationError

from workflow_orchestration_queue.config.settings import Settings, get_settings


class TestSettingsValidation:
    """Tests for Settings validation behavior."""

    def test_settings_with_valid_config(self, mock_env_vars: None) -> None:
        """Test that Settings accepts valid configuration."""
        # Clear cache to pick up new env vars
        get_settings.cache_clear()

        settings = Settings()

        assert settings.github_token == "ghp_test_token_for_testing_12345"
        assert settings.github_repo == "test-owner/test-repo"
        assert settings.sentinel_bot_login == "test-bot"
        assert settings.poll_interval == 60
        assert settings.environment == "development"

    def test_settings_missing_required_var(self) -> None:
        """Test that Settings raises error when required vars are missing."""
        # Clear all relevant env vars
        original = os.environ.get("GITHUB_TOKEN")
        if "GITHUB_TOKEN" in os.environ:
            del os.environ["GITHUB_TOKEN"]

        try:
            with pytest.raises(ValidationError) as exc_info:
                Settings()

            assert "github_token" in str(exc_info.value).lower()
        finally:
            if original:
                os.environ["GITHUB_TOKEN"] = original

    def test_settings_rejects_placeholder_token(self) -> None:
        """Test that Settings rejects placeholder token values."""
        original = os.environ.get("GITHUB_TOKEN")
        os.environ["GITHUB_TOKEN"] = "your-token-here"

        try:
            with pytest.raises(ValidationError) as exc_info:
                Settings()

            assert "placeholder" in str(exc_info.value).lower()
        finally:
            if original:
                os.environ["GITHUB_TOKEN"] = original
            elif "GITHUB_TOKEN" in os.environ:
                del os.environ["GITHUB_TOKEN"]

    def test_settings_validates_repo_format(self) -> None:
        """Test that Settings validates owner/repo format."""
        original = os.environ.get("GITHUB_REPO")
        os.environ["GITHUB_REPO"] = "invalid-repo-format"

        try:
            with pytest.raises(ValidationError) as exc_info:
                Settings()

            assert "owner/repo" in str(exc_info.value)
        finally:
            if original:
                os.environ["GITHUB_REPO"] = original
            elif "GITHUB_REPO" in os.environ:
                del os.environ["GITHUB_REPO"]

    def test_settings_validates_log_level(self) -> None:
        """Test that Settings validates log level values."""
        original = os.environ.get("LOG_LEVEL")
        os.environ["LOG_LEVEL"] = "INVALID"

        try:
            with pytest.raises(ValidationError) as exc_info:
                Settings()

            assert "log level" in str(exc_info.value).lower()
        finally:
            if original:
                os.environ["LOG_LEVEL"] = original
            elif "LOG_LEVEL" in os.environ:
                del os.environ["LOG_LEVEL"]

    def test_settings_uses_defaults(self, mock_env_vars: None) -> None:
        """Test that Settings uses default values for optional vars."""
        get_settings.cache_clear()

        settings = Settings()

        assert settings.poll_interval == 60
        assert settings.max_backoff == 960
        assert settings.heartbeat_interval == 300
        assert settings.subprocess_timeout == 5700
        assert settings.log_level == "INFO"
        assert settings.environment == "development"


class TestSettingsCaching:
    """Tests for Settings caching behavior."""

    def test_get_settings_caches_result(self, mock_env_vars: None) -> None:
        """Test that get_settings returns cached instance."""
        get_settings.cache_clear()

        settings1 = get_settings()
        settings2 = get_settings()

        assert settings1 is settings2
