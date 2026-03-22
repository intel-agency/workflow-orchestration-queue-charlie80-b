"""
Unit tests for GitHubQueue class.

Tests cover:
- fetch_queued_tasks() with mock httpx
- update_status() label transitions
- claim_task() distributed locking
- claim_task_with_retry() with exponential backoff
- Rate limit handling (403/429)
- Connection pool cleanup
- LockingConfig from environment
- API error handling (404, 403, 422)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from workflow_orchestration_queue.models.work_item import (
    TaskType,
    WorkItem,
    WorkItemStatus,
)
from workflow_orchestration_queue.queue.github_queue import (
    AssignmentError,
    ContentionError,
    GitHubQueue,
    ITaskQueue,
    LockingConfig,
    VerificationError,
)


@pytest.fixture
def mock_httpx_client():
    """Create a mock httpx.AsyncClient."""
    client = AsyncMock(spec=httpx.AsyncClient)
    return client


@pytest.fixture
def github_queue(mock_httpx_client):
    """Create a GitHubQueue instance with mocked client."""
    config = LockingConfig(bot_login="")  # Default config without bot login
    queue = GitHubQueue(token="test-token", org="test-org", repo="test-repo", config=config)
    queue._client = mock_httpx_client
    return queue


@pytest.fixture
def sample_work_item():
    """Create a sample WorkItem for testing."""
    return WorkItem(
        id="12345",
        issue_number=42,
        source_url="https://github.com/test-org/test-repo/issues/42",
        context_body="Test task body",
        target_repo_slug="test-org/test-repo",
        task_type=TaskType.IMPLEMENT,
        status=WorkItemStatus.QUEUED,
        node_id="I_kwDO12345",
    )


@pytest.fixture
def sample_github_issue():
    """Create a sample GitHub issue response."""
    return {
        "id": 12345,
        "number": 42,
        "html_url": "https://github.com/test-org/test-repo/issues/42",
        "body": "Test task body",
        "node_id": "I_kwDO12345",
        "labels": [{"name": "agent:queued"}],
        "title": "Test Issue",
    }


class TestGitHubQueueInit:
    """Tests for GitHubQueue initialization."""

    @pytest.mark.unit
    def test_init_with_all_params(self):
        """Test initialization with all parameters."""
        queue = GitHubQueue(token="my-token", org="my-org", repo="my-repo")
        assert queue.token == "my-token"
        assert queue.org == "my-org"
        assert queue.repo == "my-repo"
        assert queue.headers["Authorization"] == "token my-token"
        assert queue._client is not None

    @pytest.mark.unit
    def test_init_with_defaults(self):
        """Test initialization with default org/repo."""
        queue = GitHubQueue(token="my-token")
        assert queue.token == "my-token"
        assert queue.org == ""
        assert queue.repo == ""


class TestGitHubQueueClose:
    """Tests for connection pool cleanup."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_close_releases_client(self):
        """Test that close() releases the HTTP client."""
        queue = GitHubQueue(token="test-token", org="test-org", repo="test-repo")
        assert queue._client is not None

        await queue.close()

        assert queue._client is None

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_close_idempotent(self):
        """Test that close() can be called multiple times safely."""
        queue = GitHubQueue(token="test-token", org="test-org", repo="test-repo")

        await queue.close()
        await queue.close()  # Should not raise

        assert queue._client is None

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_operations_after_close_return_early(self, sample_work_item):
        """Test that operations after close handle gracefully."""
        queue = GitHubQueue(token="test-token", org="test-org", repo="test-repo")
        await queue.close()

        # fetch_queued_tasks should return empty list
        tasks = await queue.fetch_queued_tasks()
        assert tasks == []

        # add_to_queue should return False
        result = await queue.add_to_queue(sample_work_item)
        assert result is False

        # update_status should return early
        await queue.update_status(sample_work_item, WorkItemStatus.SUCCESS)  # Should not raise

        # claim_task should return False
        result = await queue.claim_task(sample_work_item, "sentinel-1")
        assert result is False


class TestFetchQueuedTasks:
    """Tests for fetch_queued_tasks method."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_fetch_queued_tasks_success(
        self, github_queue, mock_httpx_client, sample_github_issue
    ):
        """Test successful fetch of queued tasks."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [sample_github_issue]
        mock_httpx_client.get.return_value = mock_response

        tasks = await github_queue.fetch_queued_tasks()

        assert len(tasks) == 1
        assert tasks[0].issue_number == 42
        assert tasks[0].task_type == TaskType.IMPLEMENT
        assert tasks[0].status == WorkItemStatus.QUEUED

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_fetch_queued_tasks_empty(self, github_queue, mock_httpx_client):
        """Test fetch with no queued tasks."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_httpx_client.get.return_value = mock_response

        tasks = await github_queue.fetch_queued_tasks()

        assert len(tasks) == 0

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_fetch_queued_tasks_detects_plan_type(self, github_queue, mock_httpx_client):
        """Test that PLAN task type is detected from labels."""
        issue = {
            "id": 1,
            "number": 1,
            "html_url": "https://github.com/org/repo/issues/1",
            "body": "Plan task",
            "node_id": "node_1",
            "labels": [{"name": "agent:queued"}, {"name": "agent:plan"}],
            "title": "Plan: Create feature",
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [issue]
        mock_httpx_client.get.return_value = mock_response

        tasks = await github_queue.fetch_queued_tasks()

        assert tasks[0].task_type == TaskType.PLAN

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_fetch_queued_tasks_detects_plan_from_title(
        self, github_queue, mock_httpx_client
    ):
        """Test that PLAN task type is detected from title."""
        issue = {
            "id": 2,
            "number": 2,
            "html_url": "https://github.com/org/repo/issues/2",
            "body": "Plan task",
            "node_id": "node_2",
            "labels": [{"name": "agent:queued"}],
            "title": "[Plan] Create feature",
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [issue]
        mock_httpx_client.get.return_value = mock_response

        tasks = await github_queue.fetch_queued_tasks()

        assert tasks[0].task_type == TaskType.PLAN

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_fetch_queued_tasks_detects_bugfix_type(self, github_queue, mock_httpx_client):
        """Test that BUGFIX task type is detected from bug label."""
        issue = {
            "id": 3,
            "number": 3,
            "html_url": "https://github.com/org/repo/issues/3",
            "body": "Bug fix task",
            "node_id": "node_3",
            "labels": [{"name": "agent:queued"}, {"name": "bug"}],
            "title": "Fix critical bug",
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [issue]
        mock_httpx_client.get.return_value = mock_response

        tasks = await github_queue.fetch_queued_tasks()

        assert tasks[0].task_type == TaskType.BUGFIX

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_fetch_queued_tasks_handles_null_body(self, github_queue, mock_httpx_client):
        """Test handling of null body field."""
        issue = {
            "id": 4,
            "number": 4,
            "html_url": "https://github.com/org/repo/issues/4",
            "body": None,
            "node_id": "node_4",
            "labels": [{"name": "agent:queued"}],
            "title": "Issue with no body",
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [issue]
        mock_httpx_client.get.return_value = mock_response

        tasks = await github_queue.fetch_queued_tasks()

        assert tasks[0].context_body == ""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_fetch_queued_tasks_403_raises(self, github_queue, mock_httpx_client):
        """Test that 403 rate limit raises HTTPStatusError."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "rate limit exceeded"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Rate limited", request=MagicMock(), response=mock_response
        )
        mock_httpx_client.get.return_value = mock_response

        with pytest.raises(httpx.HTTPStatusError):
            await github_queue.fetch_queued_tasks()

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_fetch_queued_tasks_429_raises(self, github_queue, mock_httpx_client):
        """Test that 429 rate limit raises HTTPStatusError."""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "too many requests"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Rate limited", request=MagicMock(), response=mock_response
        )
        mock_httpx_client.get.return_value = mock_response

        with pytest.raises(httpx.HTTPStatusError):
            await github_queue.fetch_queued_tasks()

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_fetch_queued_tasks_other_error_returns_empty(
        self, github_queue, mock_httpx_client
    ):
        """Test that other HTTP errors return empty list."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal server error"
        mock_httpx_client.get.return_value = mock_response

        tasks = await github_queue.fetch_queued_tasks()

        assert tasks == []

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_fetch_queued_tasks_requires_org_repo(self, mock_httpx_client):
        """Test that fetch requires org and repo to be set."""
        queue = GitHubQueue(token="test-token")  # No org/repo
        queue._client = mock_httpx_client

        tasks = await queue.fetch_queued_tasks()

        assert tasks == []
        mock_httpx_client.get.assert_not_called()


class TestAddToQueue:
    """Tests for add_to_queue method."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_add_to_queue_success(self, github_queue, mock_httpx_client, sample_work_item):
        """Test successful add to queue."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_httpx_client.post.return_value = mock_response

        result = await github_queue.add_to_queue(sample_work_item)

        assert result is True
        mock_httpx_client.post.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_add_to_queue_created(self, github_queue, mock_httpx_client, sample_work_item):
        """Test add to queue with 201 Created status."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_httpx_client.post.return_value = mock_response

        result = await github_queue.add_to_queue(sample_work_item)

        assert result is True

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_add_to_queue_failure(self, github_queue, mock_httpx_client, sample_work_item):
        """Test add to queue with failure status."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_httpx_client.post.return_value = mock_response

        result = await github_queue.add_to_queue(sample_work_item)

        assert result is False


class TestUpdateStatus:
    """Tests for update_status method."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_update_status_success(self, github_queue, mock_httpx_client, sample_work_item):
        """Test successful status update."""
        mock_delete_response = MagicMock()
        mock_delete_response.status_code = 200
        mock_httpx_client.delete.return_value = mock_delete_response
        mock_httpx_client.post.return_value = MagicMock()

        await github_queue.update_status(sample_work_item, WorkItemStatus.SUCCESS)

        # Should call delete for in-progress label and post for new label
        assert mock_httpx_client.delete.call_count == 1
        assert mock_httpx_client.post.call_count >= 1

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_update_status_with_comment(
        self, github_queue, mock_httpx_client, sample_work_item
    ):
        """Test status update with comment."""
        mock_delete_response = MagicMock()
        mock_delete_response.status_code = 200
        mock_httpx_client.delete.return_value = mock_delete_response
        mock_httpx_client.post.return_value = MagicMock()

        await github_queue.update_status(
            sample_work_item, WorkItemStatus.SUCCESS, comment="Task completed!"
        )

        # Should post label and comment
        assert mock_httpx_client.post.call_count >= 2

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_update_status_scrubs_secrets_in_comment(
        self, github_queue, mock_httpx_client, sample_work_item
    ):
        """Test that secrets are scrubbed from comments."""
        mock_delete_response = MagicMock()
        mock_delete_response.status_code = 200
        mock_httpx_client.delete.return_value = mock_delete_response
        mock_httpx_client.post.return_value = MagicMock()

        comment_with_secret = "Token: ghp_1234567890abcdefghijklmnopqrstuvwxyz"
        await github_queue.update_status(
            sample_work_item, WorkItemStatus.SUCCESS, comment=comment_with_secret
        )

        # Check that the comment was scrubbed
        calls = mock_httpx_client.post.call_args_list
        comment_call = None
        for call in calls:
            if "body" in str(call):
                comment_call = call
                break

        assert comment_call is not None
        body = comment_call[1]["json"]["body"]
        assert "ghp_" not in body
        assert "***REDACTED***" in body

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_update_status_handles_label_not_found(
        self, github_queue, mock_httpx_client, sample_work_item
    ):
        """Test that 404 on label delete is handled gracefully."""
        mock_delete_response = MagicMock()
        mock_delete_response.status_code = 404
        mock_httpx_client.delete.return_value = mock_delete_response
        mock_httpx_client.post.return_value = MagicMock()

        # Should not raise
        await github_queue.update_status(sample_work_item, WorkItemStatus.SUCCESS)


class TestClaimTask:
    """Tests for claim_task method."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_claim_task_without_bot_login(
        self, github_queue, mock_httpx_client, sample_work_item
    ):
        """Test claim without bot login (label-only locking)."""
        mock_delete_response = MagicMock()
        mock_delete_response.status_code = 200
        mock_httpx_client.delete.return_value = mock_delete_response
        mock_httpx_client.post.return_value = MagicMock()

        result = await github_queue.claim_task(sample_work_item, "sentinel-1", bot_login="")

        assert result is True
        # Should not call assignees endpoint
        assignee_calls = [c for c in mock_httpx_client.post.call_args_list if "assignees" in str(c)]
        assert len(assignee_calls) == 0

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_claim_task_with_bot_login_success(
        self, github_queue, mock_httpx_client, sample_work_item
    ):
        """Test successful claim with assign-then-verify locking."""
        # Mock assignment
        mock_assign_response = MagicMock()
        mock_assign_response.status_code = 201

        # Mock verify response
        mock_verify_response = MagicMock()
        mock_verify_response.status_code = 200
        mock_verify_response.json.return_value = {"assignees": [{"login": "my-bot"}]}

        # Mock label operations
        mock_delete_response = MagicMock()
        mock_delete_response.status_code = 200

        mock_httpx_client.post.return_value = mock_assign_response
        mock_httpx_client.get.return_value = mock_verify_response
        mock_httpx_client.delete.return_value = mock_delete_response

        result = await github_queue.claim_task(sample_work_item, "sentinel-1", bot_login="my-bot")

        assert result is True

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_claim_task_assignment_fails(self, mock_httpx_client, sample_work_item):
        """Test claim when assignment fails with non-specific error."""
        config = LockingConfig(bot_login="my-bot")
        queue = GitHubQueue(token="test-token", org="test-org", repo="test-repo", config=config)
        queue._client = mock_httpx_client

        mock_assign_response = MagicMock()
        mock_assign_response.status_code = 500  # Generic server error (not 404/403/422)
        mock_httpx_client.post.return_value = mock_assign_response

        result = await queue.claim_task(sample_work_item, "sentinel-1")

        assert result is False

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_claim_task_lost_race(self, mock_httpx_client, sample_work_item):
        """Test claim when we lose the race to another sentinel."""
        config = LockingConfig(bot_login="my-bot")
        queue = GitHubQueue(token="test-token", org="test-org", repo="test-repo", config=config)
        queue._client = mock_httpx_client

        mock_assign_response = MagicMock()
        mock_assign_response.status_code = 201

        # Different assignee returned
        mock_verify_response = MagicMock()
        mock_verify_response.status_code = 200
        mock_verify_response.json.return_value = {"assignees": [{"login": "other-bot"}]}

        mock_httpx_client.post.return_value = mock_assign_response
        mock_httpx_client.get.return_value = mock_verify_response

        with pytest.raises(ContentionError):
            await queue.claim_task(sample_work_item, "sentinel-1")

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_claim_task_verify_fails(self, mock_httpx_client, sample_work_item):
        """Test claim when verify request fails."""
        config = LockingConfig(bot_login="my-bot")
        queue = GitHubQueue(token="test-token", org="test-org", repo="test-repo", config=config)
        queue._client = mock_httpx_client

        mock_assign_response = MagicMock()
        mock_assign_response.status_code = 201

        mock_verify_response = MagicMock()
        mock_verify_response.status_code = 500

        mock_httpx_client.post.return_value = mock_assign_response
        mock_httpx_client.get.return_value = mock_verify_response

        with pytest.raises(VerificationError):
            await queue.claim_task(sample_work_item, "sentinel-1")

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_claim_task_label_delete_fails(self, mock_httpx_client, sample_work_item):
        """Test claim when label deletion fails."""
        config = LockingConfig(bot_login="my-bot")
        queue = GitHubQueue(token="test-token", org="test-org", repo="test-repo", config=config)
        queue._client = mock_httpx_client

        mock_assign_response = MagicMock()
        mock_assign_response.status_code = 201

        mock_verify_response = MagicMock()
        mock_verify_response.status_code = 200
        mock_verify_response.json.return_value = {"assignees": [{"login": "my-bot"}]}

        mock_delete_response = MagicMock()
        mock_delete_response.status_code = 500  # Failure

        mock_httpx_client.post.return_value = mock_assign_response
        mock_httpx_client.get.return_value = mock_verify_response
        mock_httpx_client.delete.return_value = mock_delete_response

        result = await queue.claim_task(sample_work_item, "sentinel-1")

        assert result is False


class TestPostHeartbeat:
    """Tests for post_heartbeat method."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_post_heartbeat_success(self, github_queue, mock_httpx_client, sample_work_item):
        """Test successful heartbeat post."""
        mock_httpx_client.post.return_value = MagicMock()

        await github_queue.post_heartbeat(sample_work_item, "sentinel-1", elapsed_secs=300)

        mock_httpx_client.post.assert_called_once()
        call_args = mock_httpx_client.post.call_args
        assert "heartbeat" in str(call_args).lower() or "Heartbeat" in str(call_args)

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_post_heartbeat_handles_exception(
        self, github_queue, mock_httpx_client, sample_work_item
    ):
        """Test that heartbeat handles exceptions gracefully."""
        mock_httpx_client.post.side_effect = Exception("Network error")

        # Should not raise
        await github_queue.post_heartbeat(sample_work_item, "sentinel-1", elapsed_secs=300)


class TestITaskQueueInterface:
    """Tests for ITaskQueue interface compliance."""

    @pytest.mark.unit
    def test_github_queue_implements_interface(self):
        """Test that GitHubQueue implements ITaskQueue."""
        assert issubclass(GitHubQueue, ITaskQueue)

    @pytest.mark.unit
    def test_interface_has_required_methods(self):
        """Test that ITaskQueue defines required abstract methods."""
        # Check abstract methods exist
        abstract_methods = ITaskQueue.__abstractmethods__
        assert "add_to_queue" in abstract_methods
        assert "fetch_queued_tasks" in abstract_methods
        assert "update_status" in abstract_methods


class TestRepoApiUrl:
    """Tests for _repo_api_url helper method."""

    @pytest.mark.unit
    def test_repo_api_url_format(self, github_queue):
        """Test that _repo_api_url generates correct URL."""
        url = github_queue._repo_api_url("org/repo")
        assert url == "https://api.github.com/repos/org/repo"

    @pytest.mark.unit
    def test_repo_api_url_with_special_chars(self, github_queue):
        """Test _repo_api_url with org/repo containing special characters."""
        url = github_queue._repo_api_url("my-org/my-repo-123")
        assert url == "https://api.github.com/repos/my-org/my-repo-123"


class TestLockingConfig:
    """Tests for LockingConfig dataclass."""

    @pytest.mark.unit
    def test_default_values(self):
        """Test default configuration values."""
        config = LockingConfig()
        assert config.api_timeout == 30.0
        assert config.bot_login == ""
        assert config.max_retry_attempts == 3
        assert config.initial_backoff_ms == 100
        assert config.max_backoff_ms == 2000
        assert config.backoff_multiplier == 2.0

    @pytest.mark.unit
    def test_custom_values(self):
        """Test custom configuration values."""
        config = LockingConfig(
            api_timeout=60.0,
            bot_login="my-bot",
            max_retry_attempts=5,
            initial_backoff_ms=200,
            max_backoff_ms=5000,
            backoff_multiplier=1.5,
        )
        assert config.api_timeout == 60.0
        assert config.bot_login == "my-bot"
        assert config.max_retry_attempts == 5
        assert config.initial_backoff_ms == 200
        assert config.max_backoff_ms == 5000
        assert config.backoff_multiplier == 1.5

    @pytest.mark.unit
    def test_from_env_defaults(self):
        """Test from_env with no environment variables set."""
        with patch.dict("os.environ", {}, clear=True):
            config = LockingConfig.from_env()
            assert config.api_timeout == 30.0
            assert config.bot_login == ""
            assert config.max_retry_attempts == 3

    @pytest.mark.unit
    def test_from_env_custom_values(self):
        """Test from_env with custom environment variables."""
        env = {
            "GITHUB_API_TIMEOUT": "45.0",
            "SENTINEL_BOT_LOGIN": "env-bot",
            "LOCK_RETRY_MAX_ATTEMPTS": "5",
            "LOCK_RETRY_INITIAL_BACKOFF_MS": "150",
            "LOCK_RETRY_MAX_BACKOFF_MS": "3000",
            "LOCK_RETRY_BACKOFF_MULTIPLIER": "1.5",
        }
        with patch.dict("os.environ", env, clear=True):
            config = LockingConfig.from_env()
            assert config.api_timeout == 45.0
            assert config.bot_login == "env-bot"
            assert config.max_retry_attempts == 5
            assert config.initial_backoff_ms == 150
            assert config.max_backoff_ms == 3000
            assert config.backoff_multiplier == 1.5

    @pytest.mark.unit
    def test_github_queue_uses_config_timeout(self):
        """Test that GitHubQueue uses config timeout."""
        import asyncio

        config = LockingConfig(api_timeout=45.0)
        queue = GitHubQueue(token="test-token", config=config)
        # The client should have the config timeout
        assert queue._client is not None
        # httpx wraps timeout in a Timeout object
        assert queue._client.timeout == httpx.Timeout(45.0)
        # Clean up
        asyncio.get_event_loop().run_until_complete(queue.close())


class TestClaimTaskWithRetry:
    """Tests for claim_task_with_retry method."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_claim_task_with_retry_success_first_attempt(
        self, mock_httpx_client, sample_work_item
    ):
        """Test successful claim on first attempt."""
        config = LockingConfig(max_retry_attempts=3)
        queue = GitHubQueue(token="test-token", org="test-org", repo="test-repo", config=config)
        queue._client = mock_httpx_client

        # Mock successful assignment
        mock_assign_response = MagicMock()
        mock_assign_response.status_code = 201

        # Mock verify response
        mock_verify_response = MagicMock()
        mock_verify_response.status_code = 200
        mock_verify_response.json.return_value = {"assignees": [{"login": "my-bot"}]}

        # Mock label operations
        mock_delete_response = MagicMock()
        mock_delete_response.status_code = 200

        mock_httpx_client.post.return_value = mock_assign_response
        mock_httpx_client.get.return_value = mock_verify_response
        mock_httpx_client.delete.return_value = mock_delete_response

        result = await queue.claim_task_with_retry(sample_work_item, "sentinel-1", "my-bot")

        assert result is True
        # Should only be called once (no retries)
        assert mock_httpx_client.post.call_count >= 2  # assign + labels + comment

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_claim_task_with_retry_success_after_contention(
        self, mock_httpx_client, sample_work_item
    ):
        """Test successful claim after retry on contention."""
        config = LockingConfig(
            max_retry_attempts=3,
            initial_backoff_ms=10,  # Fast for testing
        )
        queue = GitHubQueue(token="test-token", org="test-org", repo="test-repo", config=config)
        queue._client = mock_httpx_client

        # First attempt: contention (other assignee)
        mock_assign_response_1 = MagicMock()
        mock_assign_response_1.status_code = 201

        mock_verify_response_1 = MagicMock()
        mock_verify_response_1.status_code = 200
        mock_verify_response_1.json.return_value = {"assignees": [{"login": "other-bot"}]}

        # Second attempt: success
        mock_assign_response_2 = MagicMock()
        mock_assign_response_2.status_code = 201

        mock_verify_response_2 = MagicMock()
        mock_verify_response_2.status_code = 200
        mock_verify_response_2.json.return_value = {"assignees": [{"login": "my-bot"}]}

        mock_delete_response = MagicMock()
        mock_delete_response.status_code = 200

        # Setup sequence of responses
        mock_httpx_client.post.side_effect = [
            mock_assign_response_1,
            mock_assign_response_2,
            MagicMock(),  # label post
            MagicMock(),  # comment post
        ]
        mock_httpx_client.get.side_effect = [mock_verify_response_1, mock_verify_response_2]
        mock_httpx_client.delete.return_value = mock_delete_response

        result = await queue.claim_task_with_retry(sample_work_item, "sentinel-1", "my-bot")

        assert result is True
        # Should have two assignment attempts
        assert mock_httpx_client.get.call_count == 2

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_claim_task_with_retry_exhausted(self, mock_httpx_client, sample_work_item):
        """Test that retries are exhausted after max attempts."""
        config = LockingConfig(
            max_retry_attempts=3,
            initial_backoff_ms=10,  # Fast for testing
        )
        queue = GitHubQueue(token="test-token", org="test-org", repo="test-repo", config=config)
        queue._client = mock_httpx_client

        # All attempts: contention
        mock_assign_response = MagicMock()
        mock_assign_response.status_code = 201

        mock_verify_response = MagicMock()
        mock_verify_response.status_code = 200
        mock_verify_response.json.return_value = {"assignees": [{"login": "other-bot"}]}

        mock_httpx_client.post.return_value = mock_assign_response
        mock_httpx_client.get.return_value = mock_verify_response

        result = await queue.claim_task_with_retry(sample_work_item, "sentinel-1", "my-bot")

        assert result is False
        # Should have 3 assignment attempts
        assert mock_httpx_client.get.call_count == 3

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_claim_task_with_retry_no_retry_on_assignment_error(
        self, mock_httpx_client, sample_work_item
    ):
        """Test that AssignmentError is not retried."""
        config = LockingConfig(max_retry_attempts=3)
        queue = GitHubQueue(token="test-token", org="test-org", repo="test-repo", config=config)
        queue._client = mock_httpx_client

        # 404 error
        mock_assign_response = MagicMock()
        mock_assign_response.status_code = 404

        mock_httpx_client.post.return_value = mock_assign_response

        with pytest.raises(AssignmentError) as exc_info:
            await queue.claim_task_with_retry(sample_work_item, "sentinel-1", "my-bot")

        assert exc_info.value.issue_number == sample_work_item.issue_number
        assert exc_info.value.context.get("status_code") == 404
        # Should only be called once (no retry)
        assert mock_httpx_client.post.call_count == 1

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_claim_task_with_retry_no_retry_on_verification_error(
        self, mock_httpx_client, sample_work_item
    ):
        """Test that VerificationError is not retried."""
        config = LockingConfig(max_retry_attempts=3)
        queue = GitHubQueue(token="test-token", org="test-org", repo="test-repo", config=config)
        queue._client = mock_httpx_client

        mock_assign_response = MagicMock()
        mock_assign_response.status_code = 201

        mock_verify_response = MagicMock()
        mock_verify_response.status_code = 500  # Server error on verify

        mock_httpx_client.post.return_value = mock_assign_response
        mock_httpx_client.get.return_value = mock_verify_response

        with pytest.raises(VerificationError) as exc_info:
            await queue.claim_task_with_retry(sample_work_item, "sentinel-1", "my-bot")

        assert exc_info.value.issue_number == sample_work_item.issue_number
        # Should only be called once (no retry)
        assert mock_httpx_client.get.call_count == 1

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_claim_task_with_retry_uses_config_bot_login(
        self, mock_httpx_client, sample_work_item
    ):
        """Test that config bot_login is used when not provided."""
        config = LockingConfig(bot_login="config-bot")
        queue = GitHubQueue(token="test-token", org="test-org", repo="test-repo", config=config)
        queue._client = mock_httpx_client

        mock_assign_response = MagicMock()
        mock_assign_response.status_code = 201

        mock_verify_response = MagicMock()
        mock_verify_response.status_code = 200
        mock_verify_response.json.return_value = {"assignees": [{"login": "config-bot"}]}

        mock_delete_response = MagicMock()
        mock_delete_response.status_code = 200

        mock_httpx_client.post.return_value = mock_assign_response
        mock_httpx_client.get.return_value = mock_verify_response
        mock_httpx_client.delete.return_value = mock_delete_response

        result = await queue.claim_task_with_retry(
            sample_work_item, "sentinel-1"
        )  # No bot_login provided

        assert result is True
        # Check that config bot was used
        call_args = mock_httpx_client.post.call_args_list[0]
        assert "config-bot" in str(call_args)


class TestAPIErrorHandling:
    """Tests for specific API error handling."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_claim_task_404_not_found(self, mock_httpx_client, sample_work_item):
        """Test 404 Not Found error handling."""
        config = LockingConfig(bot_login="my-bot")
        queue = GitHubQueue(token="test-token", org="test-org", repo="test-repo", config=config)
        queue._client = mock_httpx_client

        mock_assign_response = MagicMock()
        mock_assign_response.status_code = 404

        mock_httpx_client.post.return_value = mock_assign_response

        with pytest.raises(AssignmentError) as exc_info:
            await queue.claim_task(sample_work_item, "sentinel-1")

        assert "not found" in str(exc_info.value).lower()
        assert exc_info.value.context.get("status_code") == 404

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_claim_task_403_forbidden(self, mock_httpx_client, sample_work_item):
        """Test 403 Forbidden error handling."""
        config = LockingConfig(bot_login="my-bot")
        queue = GitHubQueue(token="test-token", org="test-org", repo="test-repo", config=config)
        queue._client = mock_httpx_client

        mock_assign_response = MagicMock()
        mock_assign_response.status_code = 403

        mock_httpx_client.post.return_value = mock_assign_response

        with pytest.raises(AssignmentError) as exc_info:
            await queue.claim_task(sample_work_item, "sentinel-1")

        assert "permission denied" in str(exc_info.value).lower()
        assert exc_info.value.context.get("status_code") == 403

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_claim_task_422_validation_error(self, mock_httpx_client, sample_work_item):
        """Test 422 Unprocessable Entity error handling."""
        config = LockingConfig(bot_login="my-bot")
        queue = GitHubQueue(token="test-token", org="test-org", repo="test-repo", config=config)
        queue._client = mock_httpx_client

        mock_assign_response = MagicMock()
        mock_assign_response.status_code = 422
        mock_assign_response.text = '{"message": "Validation failed"}'

        mock_httpx_client.post.return_value = mock_assign_response

        with pytest.raises(AssignmentError) as exc_info:
            await queue.claim_task(sample_work_item, "sentinel-1")

        assert "validation error" in str(exc_info.value).lower()
        assert exc_info.value.context.get("status_code") == 422

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_claim_task_network_error_on_assignment(
        self, mock_httpx_client, sample_work_item
    ):
        """Test network error handling during assignment."""
        config = LockingConfig(bot_login="my-bot")
        queue = GitHubQueue(token="test-token", org="test-org", repo="test-repo", config=config)
        queue._client = mock_httpx_client

        mock_httpx_client.post.side_effect = httpx.ConnectError("Connection refused")

        with pytest.raises(AssignmentError) as exc_info:
            await queue.claim_task(sample_work_item, "sentinel-1")

        assert "network error" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_claim_task_network_error_on_verification(
        self, mock_httpx_client, sample_work_item
    ):
        """Test network error handling during verification."""
        config = LockingConfig(bot_login="my-bot")
        queue = GitHubQueue(token="test-token", org="test-org", repo="test-repo", config=config)
        queue._client = mock_httpx_client

        mock_assign_response = MagicMock()
        mock_assign_response.status_code = 201

        mock_httpx_client.post.return_value = mock_assign_response
        mock_httpx_client.get.side_effect = httpx.ReadTimeout("Read timed out")

        with pytest.raises(VerificationError) as exc_info:
            await queue.claim_task(sample_work_item, "sentinel-1")

        assert "network error" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_claim_task_verification_server_error(self, mock_httpx_client, sample_work_item):
        """Test server error during verification."""
        config = LockingConfig(bot_login="my-bot")
        queue = GitHubQueue(token="test-token", org="test-org", repo="test-repo", config=config)
        queue._client = mock_httpx_client

        mock_assign_response = MagicMock()
        mock_assign_response.status_code = 201

        mock_verify_response = MagicMock()
        mock_verify_response.status_code = 500
        mock_verify_response.text = "Internal server error"

        mock_httpx_client.post.return_value = mock_assign_response
        mock_httpx_client.get.return_value = mock_verify_response

        with pytest.raises(VerificationError) as exc_info:
            await queue.claim_task(sample_work_item, "sentinel-1")

        assert exc_info.value.context.get("status_code") == 500


class TestBackoffStrategy:
    """Tests for exponential backoff calculation."""

    @pytest.mark.unit
    def test_backoff_increases_exponentially(self):
        """Test that backoff increases with each attempt."""
        config = LockingConfig(
            initial_backoff_ms=100,
            max_backoff_ms=10000,
            backoff_multiplier=2.0,
        )
        queue = GitHubQueue(token="test-token", config=config)

        # Get multiple backoff values (without jitter for comparison)
        backoffs = []
        for attempt in range(5):
            # Run multiple times to get average (due to jitter)
            samples = [queue._calculate_backoff(attempt) for _ in range(100)]
            avg_backoff = sum(samples) / len(samples)
            backoffs.append(avg_backoff)

        # Backoff should increase (approximately) exponentially
        assert backoffs[1] > backoffs[0]
        assert backoffs[2] > backoffs[1]
        assert backoffs[3] > backoffs[2]

    @pytest.mark.unit
    def test_backoff_respects_max(self):
        """Test that backoff is capped at max_backoff_ms."""
        config = LockingConfig(
            initial_backoff_ms=100,
            max_backoff_ms=500,  # Low max for testing
            backoff_multiplier=2.0,
        )
        queue = GitHubQueue(token="test-token", config=config)

        # Even at high attempt numbers, backoff should not exceed max
        for attempt in range(10):
            backoff = queue._calculate_backoff(attempt)
            # Max backoff + 25% jitter = 625ms max
            assert backoff <= 0.65  # 650ms in seconds

    @pytest.mark.unit
    def test_backoff_has_jitter(self):
        """Test that jitter is added to backoff."""
        config = LockingConfig(
            initial_backoff_ms=100,
            max_backoff_ms=10000,
            backoff_multiplier=2.0,
        )
        queue = GitHubQueue(token="test-token", config=config)

        # Get multiple samples for same attempt
        samples = [queue._calculate_backoff(0) for _ in range(100)]

        # Samples should vary (jitter)
        unique_values = set(samples)
        assert len(unique_values) > 1  # Should have variation

        # All samples should be within expected range
        # Base: 100ms, jitter: 0-25%, so 100-125ms = 0.1-0.125s
        for sample in samples:
            assert 0.1 <= sample <= 0.125

    @pytest.mark.unit
    def test_backoff_first_attempt(self):
        """Test backoff for first attempt (attempt 0)."""
        config = LockingConfig(
            initial_backoff_ms=100,
            max_backoff_ms=10000,
            backoff_multiplier=2.0,
        )
        queue = GitHubQueue(token="test-token", config=config)

        backoff = queue._calculate_backoff(0)
        # 100ms + 0-25% jitter = 0.1-0.125s
        assert 0.1 <= backoff <= 0.125

    @pytest.mark.unit
    def test_backoff_second_attempt(self):
        """Test backoff for second attempt (attempt 1)."""
        config = LockingConfig(
            initial_backoff_ms=100,
            max_backoff_ms=10000,
            backoff_multiplier=2.0,
        )
        queue = GitHubQueue(token="test-token", config=config)

        backoff = queue._calculate_backoff(1)
        # 100ms * 2^1 = 200ms + 0-25% jitter = 0.2-0.25s
        assert 0.2 <= backoff <= 0.25


class TestConcurrentClaims:
    """Tests for concurrent claim scenarios."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_contention_error_raised_on_lost_race(self, mock_httpx_client, sample_work_item):
        """Test that ContentionError is raised when another worker wins."""
        config = LockingConfig(bot_login="my-bot")
        queue = GitHubQueue(token="test-token", org="test-org", repo="test-repo", config=config)
        queue._client = mock_httpx_client

        mock_assign_response = MagicMock()
        mock_assign_response.status_code = 201

        mock_verify_response = MagicMock()
        mock_verify_response.status_code = 200
        mock_verify_response.json.return_value = {"assignees": [{"login": "other-bot"}]}

        mock_httpx_client.post.return_value = mock_assign_response
        mock_httpx_client.get.return_value = mock_verify_response

        with pytest.raises(ContentionError) as exc_info:
            await queue.claim_task(sample_work_item, "sentinel-1")

        assert exc_info.value.issue_number == sample_work_item.issue_number
        assert exc_info.value.context.get("expected_assignee") == "my-bot"
        assert exc_info.value.context.get("actual_assignees") == ["other-bot"]

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_contention_with_multiple_assignees(self, mock_httpx_client, sample_work_item):
        """Test contention detection with multiple assignees."""
        config = LockingConfig(bot_login="my-bot")
        queue = GitHubQueue(token="test-token", org="test-org", repo="test-repo", config=config)
        queue._client = mock_httpx_client

        mock_assign_response = MagicMock()
        mock_assign_response.status_code = 201

        mock_verify_response = MagicMock()
        mock_verify_response.status_code = 200
        mock_verify_response.json.return_value = {
            "assignees": [{"login": "bot-1"}, {"login": "bot-2"}]
        }

        mock_httpx_client.post.return_value = mock_assign_response
        mock_httpx_client.get.return_value = mock_verify_response

        with pytest.raises(ContentionError) as exc_info:
            await queue.claim_task(sample_work_item, "sentinel-1")

        assert "bot-1" in exc_info.value.context.get("actual_assignees", [])
        assert "bot-2" in exc_info.value.context.get("actual_assignees", [])

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_empty_assignees_list(self, mock_httpx_client, sample_work_item):
        """Test contention detection with empty assignees list."""
        config = LockingConfig(bot_login="my-bot")
        queue = GitHubQueue(token="test-token", org="test-org", repo="test-repo", config=config)
        queue._client = mock_httpx_client

        mock_assign_response = MagicMock()
        mock_assign_response.status_code = 201

        mock_verify_response = MagicMock()
        mock_verify_response.status_code = 200
        mock_verify_response.json.return_value = {"assignees": []}

        mock_httpx_client.post.return_value = mock_assign_response
        mock_httpx_client.get.return_value = mock_verify_response

        with pytest.raises(ContentionError):
            await queue.claim_task(sample_work_item, "sentinel-1")

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_simulated_concurrent_claim_race(self, mock_httpx_client, sample_work_item):
        """Simulate a race condition between two sentinels."""
        config = LockingConfig(
            bot_login="sentinel-a",
            max_retry_attempts=2,
            initial_backoff_ms=10,
        )
        queue = GitHubQueue(token="test-token", org="test-org", repo="test-repo", config=config)
        queue._client = mock_httpx_client

        # First attempt: sentinel-a loses race
        # Second attempt: sentinel-a wins
        call_count = 0

        def mock_get_side_effect(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            response = MagicMock()
            response.status_code = 200
            if call_count == 1:
                response.json.return_value = {"assignees": [{"login": "sentinel-b"}]}
            else:
                response.json.return_value = {"assignees": [{"login": "sentinel-a"}]}
            return response

        mock_assign_response = MagicMock()
        mock_assign_response.status_code = 201

        mock_delete_response = MagicMock()
        mock_delete_response.status_code = 200

        mock_httpx_client.post.return_value = mock_assign_response
        mock_httpx_client.get.side_effect = mock_get_side_effect
        mock_httpx_client.delete.return_value = mock_delete_response

        result = await queue.claim_task_with_retry(sample_work_item, "sentinel-1")

        assert result is True
        assert call_count == 2  # Two verification attempts


class TestExceptionContext:
    """Tests for exception context preservation."""

    @pytest.mark.unit
    def test_assignment_error_preserves_context(self):
        """Test that AssignmentError preserves context."""
        error = AssignmentError(
            "Test error",
            issue_number=42,
            status_code=404,
            bot_login="test-bot",
        )

        assert error.issue_number == 42
        assert error.context["status_code"] == 404
        assert error.context["bot_login"] == "test-bot"

    @pytest.mark.unit
    def test_contention_error_preserves_context(self):
        """Test that ContentionError preserves context."""
        error = ContentionError(
            "Lost race",
            issue_number=42,
            expected_assignee="bot-a",
            actual_assignees=["bot-b"],
        )

        assert error.issue_number == 42
        assert error.context["expected_assignee"] == "bot-a"
        assert error.context["actual_assignees"] == ["bot-b"]

    @pytest.mark.unit
    def test_verification_error_preserves_context(self):
        """Test that VerificationError preserves context."""
        error = VerificationError(
            "Verification failed",
            issue_number=42,
            status_code=500,
        )

        assert error.issue_number == 42
        assert error.context["status_code"] == 500
