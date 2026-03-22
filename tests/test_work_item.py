"""
Tests for OS-APOW Work Item Model
"""

from src.models.work_item import TaskType, WorkItem, WorkItemStatus, scrub_secrets


class TestTaskType:
    """Tests for TaskType enum."""

    def test_task_type_values(self):
        """Verify TaskType has expected values."""
        assert TaskType.PLAN.value == "PLAN"
        assert TaskType.IMPLEMENT.value == "IMPLEMENT"
        assert TaskType.BUGFIX.value == "BUGFIX"

    def test_task_type_from_string(self):
        """Verify TaskType can be created from string."""
        assert TaskType("PLAN") == TaskType.PLAN
        assert TaskType("IMPLEMENT") == TaskType.IMPLEMENT


class TestWorkItemStatus:
    """Tests for WorkItemStatus enum."""

    def test_status_values(self):
        """Verify WorkItemStatus has expected label values."""
        assert WorkItemStatus.QUEUED.value == "agent:queued"
        assert WorkItemStatus.IN_PROGRESS.value == "agent:in-progress"
        assert WorkItemStatus.SUCCESS.value == "agent:success"
        assert WorkItemStatus.ERROR.value == "agent:error"
        assert WorkItemStatus.INFRA_FAILURE.value == "agent:infra-failure"


class TestWorkItem:
    """Tests for WorkItem model."""

    def test_create_work_item(self):
        """Verify WorkItem can be created with all fields."""
        item = WorkItem(
            id="12345",
            issue_number=42,
            source_url="https://github.com/org/repo/issues/42",
            context_body="Task description",
            target_repo_slug="org/repo",
            task_type=TaskType.PLAN,
            status=WorkItemStatus.QUEUED,
            node_id="MDExOlB1bGxSZXF1ZXN0MjM0NTY3ODk=",
        )
        assert item.id == "12345"
        assert item.issue_number == 42
        assert item.task_type == TaskType.PLAN
        assert item.status == WorkItemStatus.QUEUED

    def test_work_item_serialization(self):
        """Verify WorkItem can be serialized to dict."""
        item = WorkItem(
            id="12345",
            issue_number=42,
            source_url="https://github.com/org/repo/issues/42",
            context_body="Task description",
            target_repo_slug="org/repo",
            task_type=TaskType.IMPLEMENT,
            status=WorkItemStatus.QUEUED,
            node_id="node123",
        )
        data = item.model_dump()
        assert data["issue_number"] == 42
        assert data["task_type"] == TaskType.IMPLEMENT


class TestScrubSecrets:
    """Tests for credential scrubbing."""

    def test_scrub_github_pat(self):
        """Verify GitHub PATs are scrubbed."""
        text = "Token: ghp_1234567890abcdefghijklmnopqrstuvwxyz"
        result = scrub_secrets(text)
        assert "ghp_" not in result
        assert "***REDACTED***" in result

    def test_scrub_bearer_token(self):
        """Verify Bearer tokens are scrubbed."""
        text = "Authorization: Bearer abc123xyz789"
        result = scrub_secrets(text)
        assert "Bearer" not in result or "***REDACTED***" in result

    def test_scrub_openai_key(self):
        """Verify OpenAI-style keys are scrubbed."""
        text = "API key: sk-1234567890abcdefghijklmnopqrstuv"
        result = scrub_secrets(text)
        assert "sk-" not in result
        assert "***REDACTED***" in result

    def test_scrub_preserves_normal_text(self):
        """Verify normal text is preserved."""
        text = "This is a normal log message without secrets."
        result = scrub_secrets(text)
        assert result == text

    def test_scrub_custom_replacement(self):
        """Verify custom replacement string works."""
        text = "Token: ghp_1234567890abcdefghijklmnopqrstuvwxyz"
        result = scrub_secrets(text, replacement="[HIDDEN]")
        assert "[HIDDEN]" in result
