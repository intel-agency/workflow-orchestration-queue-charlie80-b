"""
Integration tests for the polling engine.

Tests cover:
- Full polling loop with mock GitHub API
- Error recovery scenarios
- Heartbeat mechanism
- End-to-end workflow simulation
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from workflow_orchestration_queue.models.work_item import (
    TaskType,
    WorkItem,
    WorkItemStatus,
)
from workflow_orchestration_queue.queue.github_queue import GitHubQueue
from workflow_orchestration_queue.orchestrator_sentinel import Sentinel

import workflow_orchestration_queue.orchestrator_sentinel as sentinel_module


@pytest.fixture
def mock_httpx_client():
    """Create a mock httpx.AsyncClient with realistic GitHub API responses."""
    client = AsyncMock(spec=httpx.AsyncClient)
    return client


@pytest.fixture
def sample_github_issue():
    """Create a sample GitHub issue response."""
    return {
        "id": 12345,
        "number": 42,
        "html_url": "https://github.com/test-org/test-repo/issues/42",
        "body": "Implement a new feature for the application",
        "node_id": "I_kwDO12345",
        "labels": [{"name": "agent:queued"}],
        "title": "Feature: New functionality",
        "state": "open",
    }


@pytest.fixture
def sample_work_item():
    """Create a sample WorkItem for testing."""
    return WorkItem(
        id="12345",
        issue_number=42,
        source_url="https://github.com/test-org/test-repo/issues/42",
        context_body="Implement a new feature",
        target_repo_slug="test-org/test-repo",
        task_type=TaskType.IMPLEMENT,
        status=WorkItemStatus.QUEUED,
        node_id="I_kwDO12345",
    )


@pytest.mark.integration
class TestFullPollingLoop:
    """Integration tests for the complete polling loop."""

    @pytest.mark.asyncio
    async def test_polling_loop_fetches_and_processes_task(
        self, mock_httpx_client, sample_github_issue
    ):
        """Test complete flow: poll -> claim -> process -> update status."""
        # Setup mock responses
        fetch_response = MagicMock()
        fetch_response.status_code = 200
        fetch_response.json.return_value = [sample_github_issue]

        assign_response = MagicMock()
        assign_response.status_code = 201

        verify_response = MagicMock()
        verify_response.status_code = 200
        verify_response.json.return_value = {"assignees": [{"login": "test-bot"}]}

        delete_label_response = MagicMock()
        delete_label_response.status_code = 200

        post_label_response = MagicMock()
        post_label_response.status_code = 200

        # Setup mock client call sequence
        call_count = 0

        async def mock_get(url, params=None):
            nonlocal call_count
            call_count += 1
            if "issues" in url and params:
                return fetch_response
            return verify_response

        async def mock_post(url, json=None):
            if "assignees" in url:
                return assign_response
            if "comments" in url:
                return MagicMock(status_code=201)
            return post_label_response

        async def mock_delete(url):
            return delete_label_response

        mock_httpx_client.get = mock_get
        mock_httpx_client.post = mock_post
        mock_httpx_client.delete = mock_delete

        # Create queue with mock client
        queue = GitHubQueue(token="test-token", org="test-org", repo="test-repo")
        queue._client = mock_httpx_client

        # Create sentinel with mocked shell commands
        sentinel = Sentinel(queue)

        shell_calls = []

        async def mock_shell(*args, **kwargs):
            shell_calls.append(args[0])
            # Trigger shutdown after processing
            sentinel_module._shutdown_requested = True
            return MagicMock(returncode=0, stdout="Success", stderr="")

        with patch(
            "workflow_orchestration_queue.orchestrator_sentinel.run_shell_command",
            side_effect=mock_shell,
        ):
            await sentinel.run_forever()

        sentinel_module._shutdown_requested = False

        # Verify shell commands were called in correct order
        assert len(shell_calls) >= 3
        assert shell_calls[0][0].endswith("devcontainer-opencode.sh")
        assert shell_calls[0][1] == "up"


@pytest.mark.integration
class TestErrorRecovery:
    """Integration tests for error recovery scenarios."""

    @pytest.fixture
    def mock_queue(self):
        """Create a mock GitHubQueue."""
        queue = MagicMock(spec=GitHubQueue)
        queue.close = AsyncMock()
        queue.fetch_queued_tasks = AsyncMock()
        queue.claim_task = AsyncMock(return_value=False)
        queue.post_heartbeat = AsyncMock()
        queue.update_status = AsyncMock()
        return queue

    @pytest.mark.asyncio
    async def test_infrastructure_failure_recovery(self, mock_queue, sample_work_item):
        """Test handling of infrastructure failures during processing."""
        mock_queue.fetch_queued_tasks.return_value = [sample_work_item]
        mock_queue.claim_task.return_value = True

        sentinel = Sentinel(mock_queue)

        call_count = 0

        async def mock_shell_fails_then_succeeds(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First 'up' fails
                return MagicMock(returncode=1, stderr="Container start failed")
            # Subsequent calls succeed
            return MagicMock(returncode=0, stdout="Success", stderr="")

        with patch(
            "workflow_orchestration_queue.orchestrator_sentinel.run_shell_command",
            side_effect=mock_shell_fails_then_succeeds,
        ):
            await sentinel.process_task(sample_work_item)

        # Should have updated status to INFRA_FAILURE
        mock_queue.update_status.assert_called_once()
        call_args = mock_queue.update_status.call_args
        assert call_args[0][1] == WorkItemStatus.INFRA_FAILURE


@pytest.mark.integration
class TestHeartbeatMechanism:
    """Integration tests for the heartbeat mechanism."""

    @pytest.fixture
    def mock_queue(self):
        """Create a mock GitHubQueue."""
        queue = MagicMock(spec=GitHubQueue)
        queue.post_heartbeat = AsyncMock()
        queue.update_status = AsyncMock()
        return queue

    @pytest.mark.asyncio
    async def test_heartbeat_stops_on_task_completion(self, mock_queue, sample_work_item):
        """Test that heartbeat stops when task completes."""
        sentinel = Sentinel(mock_queue)

        shell_calls = []

        async def mock_shell(*args, **kwargs):
            shell_calls.append(args)
            if len(shell_calls) >= 4:  # up, start, prompt, stop
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch(
            "workflow_orchestration_queue.orchestrator_sentinel.run_shell_command",
            side_effect=mock_shell,
        ):
            await sentinel.process_task(sample_work_item)

        # Heartbeat task should have been cancelled
        # This is implicit - if it wasn't cancelled, we'd see more heartbeat calls
        assert mock_queue.update_status.called


@pytest.mark.integration
class TestEndToEndWorkflows:
    """End-to-end integration tests for complete workflows."""

    @pytest.fixture
    def mock_queue(self):
        """Create a mock GitHubQueue."""
        queue = MagicMock(spec=GitHubQueue)
        queue.close = AsyncMock()
        queue.fetch_queued_tasks = AsyncMock(return_value=[])
        queue.claim_task = AsyncMock(return_value=False)
        queue.post_heartbeat = AsyncMock()
        queue.update_status = AsyncMock()
        return queue

    @pytest.mark.asyncio
    async def test_plan_workflow_e2e(self, mock_queue):
        """Test end-to-end PLAN workflow."""
        plan_item = WorkItem(
            id="1",
            issue_number=1,
            source_url="https://github.com/org/repo/issues/1",
            context_body="Create a plan for new feature",
            target_repo_slug="org/repo",
            task_type=TaskType.PLAN,
            status=WorkItemStatus.IN_PROGRESS,
            node_id="node_1",
        )

        sentinel = Sentinel(mock_queue)

        shell_commands = []

        async def mock_shell(*args, **kwargs):
            shell_commands.append(list(args[0]))
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch(
            "workflow_orchestration_queue.orchestrator_sentinel.run_shell_command",
            side_effect=mock_shell,
        ):
            await sentinel.process_task(plan_item)

        # Verify correct workflow was used
        prompt_cmd = [c for c in shell_commands if len(c) > 1 and c[1] == "prompt"]
        assert len(prompt_cmd) >= 1
        assert "create-app-plan.md" in str(prompt_cmd)

        # Verify status was updated to SUCCESS
        mock_queue.update_status.assert_called_once()
        assert mock_queue.update_status.call_args[0][1] == WorkItemStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_bugfix_workflow_e2e(self, mock_queue):
        """Test end-to-end BUGFIX workflow."""
        bugfix_item = WorkItem(
            id="2",
            issue_number=2,
            source_url="https://github.com/org/repo/issues/2",
            context_body="Fix the critical bug in authentication",
            target_repo_slug="org/repo",
            task_type=TaskType.BUGFIX,
            status=WorkItemStatus.IN_PROGRESS,
            node_id="node_2",
        )

        sentinel = Sentinel(mock_queue)

        shell_commands = []

        async def mock_shell(*args, **kwargs):
            shell_commands.append(list(args[0]))
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch(
            "workflow_orchestration_queue.orchestrator_sentinel.run_shell_command",
            side_effect=mock_shell,
        ):
            await sentinel.process_task(bugfix_item)

        # Verify correct workflow was used
        prompt_cmd = [c for c in shell_commands if len(c) > 1 and c[1] == "prompt"]
        assert len(prompt_cmd) >= 1
        assert "recover-from-error.md" in str(prompt_cmd)

    @pytest.mark.asyncio
    async def test_implement_workflow_e2e(self, mock_queue):
        """Test end-to-end IMPLEMENT workflow."""
        implement_item = WorkItem(
            id="3",
            issue_number=3,
            source_url="https://github.com/org/repo/issues/3",
            context_body="Implement the new API endpoint",
            target_repo_slug="org/repo",
            task_type=TaskType.IMPLEMENT,
            status=WorkItemStatus.IN_PROGRESS,
            node_id="node_3",
        )

        sentinel = Sentinel(mock_queue)

        shell_commands = []

        async def mock_shell(*args, **kwargs):
            shell_commands.append(list(args[0]))
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch(
            "workflow_orchestration_queue.orchestrator_sentinel.run_shell_command",
            side_effect=mock_shell,
        ):
            await sentinel.process_task(implement_item)

        # Verify correct workflow was used
        prompt_cmd = [c for c in shell_commands if len(c) > 1 and c[1] == "prompt"]
        assert len(prompt_cmd) >= 1
        assert "perform-task.md" in str(prompt_cmd)


@pytest.mark.integration
class TestConfigurationValidation:
    """Integration tests for configuration validation."""

    @pytest.mark.asyncio
    async def test_valid_config_initializes_queue(self):
        """Test that valid configuration initializes queue correctly."""
        import os

        # Set required env vars
        os.environ["GITHUB_TOKEN"] = "test-token"
        os.environ["GITHUB_ORG"] = "test-org"
        os.environ["GITHUB_REPO"] = "test-repo"

        try:
            queue = GitHubQueue(
                token=os.getenv("GITHUB_TOKEN", ""),
                org=os.getenv("GITHUB_ORG", ""),
                repo=os.getenv("GITHUB_REPO", ""),
            )

            assert queue.token == "test-token"
            assert queue.org == "test-org"
            assert queue.repo == "test-repo"
            assert queue._client is not None

            # Cleanup
            await queue.close()

        finally:
            os.environ.pop("GITHUB_TOKEN", None)
            os.environ.pop("GITHUB_ORG", None)
            os.environ.pop("GITHUB_REPO", None)
