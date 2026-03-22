"""
Unit tests for GitHubQueue class.

Tests cover:
- fetch_queued_tasks() with mock httpx
- update_status() label transitions
- claim_task() distributed locking
- Rate limit handling (403/429)
- Connection pool cleanup
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from workflow_orchestration_queue.models.work_item import (
    TaskType,
    WorkItem,
    WorkItemStatus,
)
from workflow_orchestration_queue.queue.github_queue import GitHubQueue, ITaskQueue


@pytest.fixture
def mock_httpx_client():
    """Create a mock httpx.AsyncClient."""
    client = AsyncMock(spec=httpx.AsyncClient)
    return client


@pytest.fixture
def github_queue(mock_httpx_client):
    """Create a GitHubQueue instance with mocked client."""
    queue = GitHubQueue(token="test-token", org="test-org", repo="test-repo")
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
    async def test_claim_task_assignment_fails(
        self, github_queue, mock_httpx_client, sample_work_item
    ):
        """Test claim when assignment fails."""
        mock_assign_response = MagicMock()
        mock_assign_response.status_code = 422
        mock_httpx_client.post.return_value = mock_assign_response

        result = await github_queue.claim_task(sample_work_item, "sentinel-1", bot_login="my-bot")

        assert result is False

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_claim_task_lost_race(self, github_queue, mock_httpx_client, sample_work_item):
        """Test claim when we lose the race to another sentinel."""
        mock_assign_response = MagicMock()
        mock_assign_response.status_code = 201

        # Different assignee returned
        mock_verify_response = MagicMock()
        mock_verify_response.status_code = 200
        mock_verify_response.json.return_value = {"assignees": [{"login": "other-bot"}]}

        mock_httpx_client.post.return_value = mock_assign_response
        mock_httpx_client.get.return_value = mock_verify_response

        result = await github_queue.claim_task(sample_work_item, "sentinel-1", bot_login="my-bot")

        assert result is False

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_claim_task_verify_fails(self, github_queue, mock_httpx_client, sample_work_item):
        """Test claim when verify request fails."""
        mock_assign_response = MagicMock()
        mock_assign_response.status_code = 201

        mock_verify_response = MagicMock()
        mock_verify_response.status_code = 500

        mock_httpx_client.post.return_value = mock_assign_response
        mock_httpx_client.get.return_value = mock_verify_response

        result = await github_queue.claim_task(sample_work_item, "sentinel-1", bot_login="my-bot")

        assert result is False

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_claim_task_label_delete_fails(
        self, github_queue, mock_httpx_client, sample_work_item
    ):
        """Test claim when label deletion fails."""
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

        result = await github_queue.claim_task(sample_work_item, "sentinel-1", bot_login="my-bot")

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
        import inspect

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
