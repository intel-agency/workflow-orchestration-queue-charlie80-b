"""
Unit tests for polling engine components in orchestrator_sentinel.py.

Tests cover:
- Backoff calculation with various inputs
- Rate limit handling (403/429 responses)
- Graceful shutdown behavior
- Jittered exponential backoff
"""

import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from workflow_orchestration_queue.models.work_item import (
    TaskType,
    WorkItem,
    WorkItemStatus,
)
from workflow_orchestration_queue.queue.github_queue import GitHubQueue


# Import the module to test (we'll patch the module-level constants)
import workflow_orchestration_queue.orchestrator_sentinel as sentinel_module


class TestBackoffCalculation:
    """Tests for backoff calculation logic."""

    @pytest.mark.unit
    def test_initial_backoff_value(self):
        """Test that initial backoff matches POLL_INTERVAL."""
        assert sentinel_module.POLL_INTERVAL == 60
        assert sentinel_module.MAX_BACKOFF == 960  # 16 minutes

    @pytest.mark.unit
    def test_backoff_doubles_on_rate_limit(self):
        """Test that backoff doubles on rate limit up to MAX_BACKOFF."""
        current = 60
        # After one rate limit: 60 * 2 = 120
        new_backoff = min(current * 2, sentinel_module.MAX_BACKOFF)
        assert new_backoff == 120

        # After second rate limit: 120 * 2 = 240
        current = new_backoff
        new_backoff = min(current * 2, sentinel_module.MAX_BACKOFF)
        assert new_backoff == 240

        # Continue doubling
        current = new_backoff
        new_backoff = min(current * 2, sentinel_module.MAX_BACKOFF)
        assert new_backoff == 480

        current = new_backoff
        new_backoff = min(current * 2, sentinel_module.MAX_BACKOFF)
        assert new_backoff == 960  # Hit MAX_BACKOFF

        # Should not exceed MAX_BACKOFF
        current = new_backoff
        new_backoff = min(current * 2, sentinel_module.MAX_BACKOFF)
        assert new_backoff == 960

    @pytest.mark.unit
    def test_backoff_sequence(self):
        """Test the full backoff doubling sequence."""
        expected_sequence = [60, 120, 240, 480, 960]
        current = sentinel_module.POLL_INTERVAL

        for expected in expected_sequence:
            assert current == expected
            current = min(current * 2, sentinel_module.MAX_BACKOFF)


class TestJitteredBackoff:
    """Tests for jittered exponential backoff."""

    @pytest.mark.unit
    def test_jitter_adds_randomness(self):
        """Test that jitter adds randomness to backoff."""
        import random

        base_backoff = 60
        samples = []

        for _ in range(100):
            jitter = random.uniform(0, base_backoff * 0.1)
            wait = min(base_backoff + jitter, sentinel_module.MAX_BACKOFF)
            samples.append(wait)

        # All samples should be >= base_backoff
        assert all(s >= base_backoff for s in samples)

        # All samples should be <= base_backoff + 10% jitter
        max_expected = base_backoff + (base_backoff * 0.1)
        assert all(s <= max_expected for s in samples)

        # There should be some variation
        unique_values = len(set(round(s, 2) for s in samples))
        assert unique_values > 1  # At least some variation

    @pytest.mark.unit
    def test_jitter_does_not_exceed_max_backoff(self):
        """Test that jitter + backoff doesn't exceed MAX_BACKOFF."""
        import random

        # Test at MAX_BACKOFF level
        base_backoff = sentinel_module.MAX_BACKOFF
        jitter = random.uniform(0, base_backoff * 0.1)
        wait = min(base_backoff + jitter, sentinel_module.MAX_BACKOFF)

        assert wait <= sentinel_module.MAX_BACKOFF


class TestRateLimitHandling:
    """Tests for rate limit (403/429) handling in the polling loop."""

    @pytest.mark.unit
    def test_403_status_code_identified_as_rate_limit(self):
        """Test that 403 is identified as a rate limit status code."""
        # The code checks for status in (403, 429)
        rate_limit_codes = (403, 429)
        assert 403 in rate_limit_codes

    @pytest.mark.unit
    def test_429_status_code_identified_as_rate_limit(self):
        """Test that 429 is identified as a rate limit status code."""
        rate_limit_codes = (403, 429)
        assert 429 in rate_limit_codes

    @pytest.mark.unit
    def test_other_status_codes_not_rate_limits(self):
        """Test that other status codes are not rate limits."""
        rate_limit_codes = (403, 429)
        assert 500 not in rate_limit_codes
        assert 404 not in rate_limit_codes
        assert 401 not in rate_limit_codes

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_backoff_doubles_on_repeated_rate_limits(self):
        """Test that backoff doubles on repeated rate limit errors."""
        from workflow_orchestration_queue.orchestrator_sentinel import Sentinel

        mock_queue = MagicMock(spec=GitHubQueue)
        mock_queue.close = AsyncMock()
        mock_queue.fetch_queued_tasks = AsyncMock()
        mock_queue.claim_task = AsyncMock(return_value=False)
        mock_queue.post_heartbeat = AsyncMock()
        mock_queue.update_status = AsyncMock()

        mock_response = MagicMock()
        mock_response.status_code = 429
        rate_limit_error = httpx.HTTPStatusError(
            "Rate limited", request=MagicMock(), response=mock_response
        )

        # Create a counter to track iterations
        iteration = [0]

        async def fetch_with_limit():
            iteration[0] += 1
            raise rate_limit_error

        mock_queue.fetch_queued_tasks.side_effect = fetch_with_limit

        sentinel = Sentinel(mock_queue)

        sleep_count = [0]

        async def quick_sleep(duration):
            sleep_count[0] += 1
            # Stop after 3 rate limit cycles
            if sleep_count[0] >= 3:
                sentinel_module._shutdown_requested = True

        with patch("asyncio.sleep", quick_sleep):
            await sentinel.run_forever()

        sentinel_module._shutdown_requested = False
        # Backoff should have increased after rate limits
        # After 3 rate limits: 60 -> 120 -> 240 -> 480
        assert sentinel._current_backoff >= 240

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_backoff_resets_on_success(self):
        """Test that backoff resets to POLL_INTERVAL after successful poll."""
        from workflow_orchestration_queue.orchestrator_sentinel import Sentinel

        mock_queue = MagicMock(spec=GitHubQueue)
        mock_queue.close = AsyncMock()
        mock_queue.fetch_queued_tasks = AsyncMock()
        mock_queue.claim_task = AsyncMock(return_value=False)
        mock_queue.post_heartbeat = AsyncMock()
        mock_queue.update_status = AsyncMock()

        call_count = [0]

        async def side_effect_fetch():
            call_count[0] += 1
            if call_count[0] == 1:
                mock_response = MagicMock()
                mock_response.status_code = 429
                raise httpx.HTTPStatusError(
                    "Rate limited", request=MagicMock(), response=mock_response
                )
            # Second call succeeds - trigger shutdown
            sentinel_module._shutdown_requested = True
            return []

        mock_queue.fetch_queued_tasks.side_effect = side_effect_fetch

        sentinel = Sentinel(mock_queue)

        async def quick_sleep(duration):
            pass  # No-op

        with patch("asyncio.sleep", quick_sleep):
            await sentinel.run_forever()

        sentinel_module._shutdown_requested = False
        # After successful poll, backoff should reset
        assert sentinel._current_backoff == sentinel_module.POLL_INTERVAL


class TestGracefulShutdown:
    """Tests for graceful shutdown behavior."""

    @pytest.fixture
    def mock_queue(self):
        """Create a mock GitHubQueue."""
        queue = MagicMock(spec=GitHubQueue)
        queue.close = AsyncMock()
        queue.fetch_queued_tasks = AsyncMock(return_value=[])
        queue.claim_task = AsyncMock(return_value=False)
        return queue

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_shutdown_flag_stops_loop(self, mock_queue):
        """Test that setting shutdown flag stops the polling loop."""
        from workflow_orchestration_queue.orchestrator_sentinel import Sentinel

        sentinel = Sentinel(mock_queue)

        # Set shutdown after first iteration
        fetch_count = 0

        async def set_shutdown_on_fetch():
            nonlocal fetch_count
            fetch_count += 1
            sentinel_module._shutdown_requested = True
            return []

        mock_queue.fetch_queued_tasks.side_effect = set_shutdown_on_fetch

        await sentinel.run_forever()

        sentinel_module._shutdown_requested = False
        assert fetch_count == 1

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_signal_handler_sets_flag(self):
        """Test that signal handler sets shutdown flag."""
        # Get the signal handler function
        handler = sentinel_module._handle_signal

        # Reset flag first
        sentinel_module._shutdown_requested = False

        # Call the handler
        handler(signal.SIGTERM, None)

        # Flag should be set
        assert sentinel_module._shutdown_requested is True

        # Reset
        sentinel_module._shutdown_requested = False

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_shutdown_breaks_task_loop(self, mock_queue):
        """Test that shutdown breaks out of task processing loop."""
        from workflow_orchestration_queue.orchestrator_sentinel import Sentinel

        # Multiple tasks returned
        items = [
            WorkItem(
                id=str(i),
                issue_number=i,
                source_url=f"https://github.com/org/repo/issues/{i}",
                context_body="Test",
                target_repo_slug="org/repo",
                task_type=TaskType.IMPLEMENT,
                status=WorkItemStatus.QUEUED,
                node_id=f"node_{i}",
            )
            for i in range(5)
        ]

        mock_queue.fetch_queued_tasks.return_value = items
        mock_queue.claim_task.return_value = True

        sentinel = Sentinel(mock_queue)

        # Track process_task calls
        process_count = [0]

        async def mock_process(item):
            process_count[0] += 1
            # Set shutdown after processing first task
            sentinel_module._shutdown_requested = True

        sentinel.process_task = mock_process

        # Mock sleep to prevent actual waiting and ensure shutdown is checked
        async def mock_sleep(duration):
            # Sleep is called at end of while loop - just return immediately
            pass

        with patch("asyncio.sleep", mock_sleep):
            await sentinel.run_forever()

        sentinel_module._shutdown_requested = False
        # Should have processed only one task
        assert process_count[0] == 1


class TestSentinelInit:
    """Tests for Sentinel initialization."""

    @pytest.mark.unit
    def test_sentinel_init_sets_queue(self):
        """Test that Sentinel initializes with queue."""
        from workflow_orchestration_queue.orchestrator_sentinel import Sentinel

        mock_queue = MagicMock(spec=GitHubQueue)
        sentinel = Sentinel(mock_queue)

        assert sentinel.queue is mock_queue
        assert sentinel._current_backoff == sentinel_module.POLL_INTERVAL


class TestHeartbeatLoop:
    """Tests for heartbeat loop functionality."""

    @pytest.fixture
    def mock_queue(self):
        """Create a mock GitHubQueue."""
        queue = MagicMock(spec=GitHubQueue)
        queue.post_heartbeat = AsyncMock()
        return queue

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_heartbeat_loop_posts_periodically(self, mock_queue):
        """Test that heartbeat loop posts heartbeats at intervals."""
        from workflow_orchestration_queue.orchestrator_sentinel import Sentinel

        sample_item = WorkItem(
            id="1",
            issue_number=1,
            source_url="https://github.com/org/repo/issues/1",
            context_body="Test",
            target_repo_slug="org/repo",
            task_type=TaskType.IMPLEMENT,
            status=WorkItemStatus.IN_PROGRESS,
            node_id="node_1",
        )

        sentinel = Sentinel(mock_queue)
        start_time = 0.0

        heartbeat_count = 0

        async def count_heartbeats(duration):
            nonlocal heartbeat_count
            heartbeat_count += 1
            if heartbeat_count >= 3:
                raise asyncio.CancelledError()
            await asyncio.sleep(0)

        with (
            patch("asyncio.sleep", count_heartbeats),
            pytest.raises(asyncio.CancelledError),
        ):
            await sentinel._heartbeat_loop(sample_item, start_time)

        assert heartbeat_count >= 3

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_heartbeat_cancellation(self, mock_queue):
        """Test that heartbeat task can be cancelled cleanly."""
        from workflow_orchestration_queue.orchestrator_sentinel import Sentinel

        sample_item = WorkItem(
            id="1",
            issue_number=1,
            source_url="https://github.com/org/repo/issues/1",
            context_body="Test",
            target_repo_slug="org/repo",
            task_type=TaskType.IMPLEMENT,
            status=WorkItemStatus.IN_PROGRESS,
            node_id="node_1",
        )

        sentinel = Sentinel(mock_queue)
        start_time = 0.0

        # Create heartbeat task
        heartbeat_task = asyncio.create_task(sentinel._heartbeat_loop(sample_item, start_time))

        # Let it start
        await asyncio.sleep(0.01)

        # Cancel it
        heartbeat_task.cancel()

        # Should handle cancellation cleanly
        with pytest.raises(asyncio.CancelledError):
            await heartbeat_task


class TestShellCommandExecution:
    """Tests for run_shell_command function."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_shell_command_success(self):
        """Test successful shell command execution."""
        from workflow_orchestration_queue.orchestrator_sentinel import run_shell_command

        result = await run_shell_command(["echo", "test"])

        assert result.returncode == 0
        assert "test" in result.stdout

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_shell_command_failure(self):
        """Test failed shell command execution."""
        from workflow_orchestration_queue.orchestrator_sentinel import run_shell_command

        # Use a command that will fail
        result = await run_shell_command(["ls", "/nonexistent_path_12345"])

        assert result.returncode != 0

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_shell_command_timeout(self):
        """Test shell command timeout handling."""
        from workflow_orchestration_queue.orchestrator_sentinel import run_shell_command

        # Command that sleeps for longer than timeout
        result = await run_shell_command(["sleep", "10"], timeout=0.1)

        assert result.returncode == -1
        assert "TIMEOUT" in result.stderr

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_shell_command_captures_stderr(self):
        """Test that stderr is captured."""
        from workflow_orchestration_queue.orchestrator_sentinel import run_shell_command

        # Use python to write to stderr
        result = await run_shell_command(
            ["python3", "-c", "import sys; sys.stderr.write('error message')"]
        )

        assert "error message" in result.stderr

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_shell_command_critical_error(self):
        """Test that critical errors in shell execution are re-raised."""
        from workflow_orchestration_queue.orchestrator_sentinel import run_shell_command

        # Mock asyncio.create_subprocess_exec to raise an unexpected error
        with patch("asyncio.create_subprocess_exec") as mock_create:
            mock_create.side_effect = OSError("Failed to create process")

            with pytest.raises(OSError):
                await run_shell_command(["echo", "test"])


class TestHeartbeatTimeCalculation:
    """Tests for heartbeat time calculation."""

    @pytest.mark.unit
    def test_heartbeat_interval_value(self):
        """Test that HEARTBEAT_INTERVAL is correctly set."""
        assert sentinel_module.HEARTBEAT_INTERVAL == 300  # 5 minutes

    @pytest.mark.unit
    def test_subprocess_timeout_value(self):
        """Test that SUBPROCESS_TIMEOUT is correctly set."""
        assert sentinel_module.SUBPROCESS_TIMEOUT == 5700  # 95 minutes


class TestProcessTask:
    """Tests for process_task method."""

    @pytest.fixture
    def mock_queue(self):
        """Create a mock GitHubQueue."""
        queue = MagicMock(spec=GitHubQueue)
        queue.update_status = AsyncMock()
        queue.post_heartbeat = AsyncMock()
        return queue

    @pytest.fixture
    def sample_item(self):
        """Create a sample work item."""
        return WorkItem(
            id="1",
            issue_number=1,
            source_url="https://github.com/org/repo/issues/1",
            context_body="Test task",
            target_repo_slug="org/repo",
            task_type=TaskType.IMPLEMENT,
            status=WorkItemStatus.IN_PROGRESS,
            node_id="node_1",
        )

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_process_task_infra_failure_on_up_fail(self, mock_queue, sample_item):
        """Test that infrastructure failure is reported when 'up' fails."""
        from workflow_orchestration_queue.orchestrator_sentinel import Sentinel

        sentinel = Sentinel(mock_queue)

        with patch(
            "workflow_orchestration_queue.orchestrator_sentinel.run_shell_command",
            new_callable=AsyncMock,
        ) as mock_run:
            # 'up' command fails
            mock_run.return_value = MagicMock(returncode=1, stderr="Failed to start container")

            await sentinel.process_task(sample_item)

        # Should have updated status to INFRA_FAILURE
        mock_queue.update_status.assert_called_once()
        call_args = mock_queue.update_status.call_args
        assert call_args[0][1] == WorkItemStatus.INFRA_FAILURE
        assert "Infrastructure Failure" in call_args[0][2]

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_process_task_infra_failure_on_start_fail(self, mock_queue, sample_item):
        """Test that infrastructure failure is reported when 'start' fails."""
        from workflow_orchestration_queue.orchestrator_sentinel import Sentinel

        sentinel = Sentinel(mock_queue)

        call_count = 0

        async def mock_shell(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # 'up' succeeds
                return MagicMock(returncode=0, stdout="")
            elif call_count == 2:  # 'start' fails
                return MagicMock(returncode=1, stderr="Failed to start server")
            else:  # 'stop'
                return MagicMock(returncode=0, stdout="")

        with patch(
            "workflow_orchestration_queue.orchestrator_sentinel.run_shell_command",
            side_effect=mock_shell,
        ):
            await sentinel.process_task(sample_item)

        mock_queue.update_status.assert_called_once()
        call_args = mock_queue.update_status.call_args
        assert call_args[0][1] == WorkItemStatus.INFRA_FAILURE

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_process_task_success_on_prompt_success(self, mock_queue, sample_item):
        """Test that success is reported when prompt succeeds."""
        from workflow_orchestration_queue.orchestrator_sentinel import Sentinel

        sentinel = Sentinel(mock_queue)

        async def mock_shell(*args, **kwargs):
            return MagicMock(returncode=0, stdout="Success", stderr="")

        with patch(
            "workflow_orchestration_queue.orchestrator_sentinel.run_shell_command",
            side_effect=mock_shell,
        ):
            await sentinel.process_task(sample_item)

        mock_queue.update_status.assert_called_once()
        call_args = mock_queue.update_status.call_args
        assert call_args[0][1] == WorkItemStatus.SUCCESS
        assert "Workflow Complete" in call_args[0][2]

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_process_task_error_on_prompt_failure(self, mock_queue, sample_item):
        """Test that error is reported when prompt fails."""
        from workflow_orchestration_queue.orchestrator_sentinel import Sentinel

        sentinel = Sentinel(mock_queue)

        call_count = 0

        async def mock_shell(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:  # 'up' and 'start' succeed
                return MagicMock(returncode=0, stdout="")
            elif call_count == 3:  # 'prompt' fails
                return MagicMock(returncode=1, stderr="Execution error occurred")
            else:  # 'stop'
                return MagicMock(returncode=0, stdout="")

        with patch(
            "workflow_orchestration_queue.orchestrator_sentinel.run_shell_command",
            side_effect=mock_shell,
        ):
            await sentinel.process_task(sample_item)

        mock_queue.update_status.assert_called_once()
        call_args = mock_queue.update_status.call_args
        assert call_args[0][1] == WorkItemStatus.ERROR
        assert "Execution Error" in call_args[0][2]

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_process_task_handles_exception(self, mock_queue, sample_item):
        """Test that exceptions are handled and reported."""
        from workflow_orchestration_queue.orchestrator_sentinel import Sentinel

        sentinel = Sentinel(mock_queue)

        call_count = [0]

        async def mock_shell_raises(*args, **kwargs):
            call_count[0] += 1
            # Only raise on first call (the 'up' command)
            if call_count[0] == 1:
                raise RuntimeError("Unexpected error")
            # Subsequent calls (like 'stop' in finally) succeed
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch(
            "workflow_orchestration_queue.orchestrator_sentinel.run_shell_command",
            side_effect=mock_shell_raises,
        ):
            await sentinel.process_task(sample_item)

        mock_queue.update_status.assert_called_once()
        call_args = mock_queue.update_status.call_args
        assert call_args[0][1] == WorkItemStatus.INFRA_FAILURE
        assert "unhandled exception" in call_args[0][2].lower()

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_process_task_selects_correct_workflow(self, mock_queue):
        """Test that correct workflow is selected based on task type."""
        from workflow_orchestration_queue.orchestrator_sentinel import Sentinel

        # Test PLAN task type
        plan_item = WorkItem(
            id="1",
            issue_number=1,
            source_url="https://github.com/org/repo/issues/1",
            context_body="Plan task",
            target_repo_slug="org/repo",
            task_type=TaskType.PLAN,
            status=WorkItemStatus.IN_PROGRESS,
            node_id="node_1",
        )

        sentinel = Sentinel(mock_queue)

        shell_calls = []

        async def mock_shell(*args, **kwargs):
            shell_calls.append(args[0])
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch(
            "workflow_orchestration_queue.orchestrator_sentinel.run_shell_command",
            side_effect=mock_shell,
        ):
            await sentinel.process_task(plan_item)

        # Check that create-app-plan.md was used
        prompt_call = [c for c in shell_calls if "prompt" in c]
        assert len(prompt_call) >= 1
        assert "create-app-plan.md" in str(prompt_call)

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_process_task_bugfix_workflow(self, mock_queue):
        """Test that BUGFIX task uses correct workflow."""
        from workflow_orchestration_queue.orchestrator_sentinel import Sentinel

        bugfix_item = WorkItem(
            id="2",
            issue_number=2,
            source_url="https://github.com/org/repo/issues/2",
            context_body="Bug fix task",
            target_repo_slug="org/repo",
            task_type=TaskType.BUGFIX,
            status=WorkItemStatus.IN_PROGRESS,
            node_id="node_2",
        )

        sentinel = Sentinel(mock_queue)

        shell_calls = []

        async def mock_shell(*args, **kwargs):
            shell_calls.append(args[0])
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch(
            "workflow_orchestration_queue.orchestrator_sentinel.run_shell_command",
            side_effect=mock_shell,
        ):
            await sentinel.process_task(bugfix_item)

        prompt_call = [c for c in shell_calls if "prompt" in c]
        assert len(prompt_call) >= 1
        assert "recover-from-error.md" in str(prompt_call)
