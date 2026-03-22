"""
Unit tests for WorkItem model and related enums.

Tests cover:
- TaskType enum values
- WorkItemStatus enum values
- WorkItem model creation and validation
- scrub_secrets() function
"""

import pytest

from workflow_orchestration_queue.models.work_item import (
    TaskType,
    WorkItem,
    WorkItemStatus,
    scrub_secrets,
)


class TestTaskType:
    """Tests for TaskType enum."""

    @pytest.mark.unit
    def test_task_type_values(self):
        """Test that TaskType has expected enum values."""
        assert TaskType.PLAN.value == "PLAN"
        assert TaskType.IMPLEMENT.value == "IMPLEMENT"
        assert TaskType.BUGFIX.value == "BUGFIX"

    @pytest.mark.unit
    def test_task_type_count(self):
        """Test that TaskType has exactly 3 members."""
        assert len(TaskType) == 3

    @pytest.mark.unit
    def test_task_type_string_conversion(self):
        """Test TaskType string conversion works correctly."""
        assert str(TaskType.PLAN) == "PLAN"
        assert TaskType.PLAN == "PLAN"  # StrEnum allows direct comparison


class TestWorkItemStatus:
    """Tests for WorkItemStatus enum."""

    @pytest.mark.unit
    def test_work_item_status_values(self):
        """Test that WorkItemStatus has expected label values."""
        assert WorkItemStatus.QUEUED.value == "agent:queued"
        assert WorkItemStatus.IN_PROGRESS.value == "agent:in-progress"
        assert WorkItemStatus.RECONCILING.value == "agent:reconciling"
        assert WorkItemStatus.SUCCESS.value == "agent:success"
        assert WorkItemStatus.ERROR.value == "agent:error"
        assert WorkItemStatus.INFRA_FAILURE.value == "agent:infra-failure"
        assert WorkItemStatus.STALLED_BUDGET.value == "agent:stalled-budget"

    @pytest.mark.unit
    def test_work_item_status_count(self):
        """Test that WorkItemStatus has exactly 7 members."""
        assert len(WorkItemStatus) == 7

    @pytest.mark.unit
    def test_work_item_status_string_conversion(self):
        """Test WorkItemStatus string conversion works correctly."""
        assert str(WorkItemStatus.QUEUED) == "agent:queued"
        assert WorkItemStatus.IN_PROGRESS == "agent:in-progress"


class TestWorkItem:
    """Tests for WorkItem model."""

    @pytest.mark.unit
    def test_work_item_creation_minimal(self):
        """Test creating a WorkItem with required fields only."""
        item = WorkItem(
            id="12345",
            issue_number=42,
            source_url="https://github.com/org/repo/issues/42",
            context_body="Test task body",
            target_repo_slug="org/repo",
            task_type=TaskType.IMPLEMENT,
            status=WorkItemStatus.QUEUED,
            node_id="I_kwDO12345",
        )

        assert item.id == "12345"
        assert item.issue_number == 42
        assert item.source_url == "https://github.com/org/repo/issues/42"
        assert item.context_body == "Test task body"
        assert item.target_repo_slug == "org/repo"
        assert item.task_type == TaskType.IMPLEMENT
        assert item.status == WorkItemStatus.QUEUED
        assert item.node_id == "I_kwDO12345"

    @pytest.mark.unit
    def test_work_item_with_plan_task_type(self):
        """Test creating a WorkItem with PLAN task type."""
        item = WorkItem(
            id="1",
            issue_number=1,
            source_url="https://github.com/org/repo/issues/1",
            context_body="[Plan] Create new feature",
            target_repo_slug="org/repo",
            task_type=TaskType.PLAN,
            status=WorkItemStatus.QUEUED,
            node_id="node_1",
        )

        assert item.task_type == TaskType.PLAN

    @pytest.mark.unit
    def test_work_item_with_bugfix_task_type(self):
        """Test creating a WorkItem with BUGFIX task type."""
        item = WorkItem(
            id="2",
            issue_number=2,
            source_url="https://github.com/org/repo/issues/2",
            context_body="Fix critical bug",
            target_repo_slug="org/repo",
            task_type=TaskType.BUGFIX,
            status=WorkItemStatus.QUEUED,
            node_id="node_2",
        )

        assert item.task_type == TaskType.BUGFIX

    @pytest.mark.unit
    def test_work_item_empty_context_body(self):
        """Test creating a WorkItem with empty context body."""
        item = WorkItem(
            id="3",
            issue_number=3,
            source_url="https://github.com/org/repo/issues/3",
            context_body="",
            target_repo_slug="org/repo",
            task_type=TaskType.IMPLEMENT,
            status=WorkItemStatus.QUEUED,
            node_id="node_3",
        )

        assert item.context_body == ""

    @pytest.mark.unit
    def test_work_item_missing_required_field(self):
        """Test that missing required fields raise validation error."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            WorkItem(
                id="4",
                issue_number=4,
                # missing source_url
                context_body="Test",
                target_repo_slug="org/repo",
                task_type=TaskType.IMPLEMENT,
                status=WorkItemStatus.QUEUED,
                node_id="node_4",
            )

    @pytest.mark.unit
    def test_work_item_invalid_task_type(self):
        """Test that invalid task type raises validation error."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            WorkItem(
                id="5",
                issue_number=5,
                source_url="https://github.com/org/repo/issues/5",
                context_body="Test",
                target_repo_slug="org/repo",
                task_type="INVALID",  # type: ignore
                status=WorkItemStatus.QUEUED,
                node_id="node_5",
            )

    @pytest.mark.unit
    def test_work_item_invalid_status(self):
        """Test that invalid status raises validation error."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            WorkItem(
                id="6",
                issue_number=6,
                source_url="https://github.com/org/repo/issues/6",
                context_body="Test",
                target_repo_slug="org/repo",
                task_type=TaskType.IMPLEMENT,
                status="invalid-status",  # type: ignore
                node_id="node_6",
            )

    @pytest.mark.unit
    def test_work_item_model_dump(self):
        """Test that WorkItem can be serialized to dict."""
        item = WorkItem(
            id="7",
            issue_number=7,
            source_url="https://github.com/org/repo/issues/7",
            context_body="Test task",
            target_repo_slug="org/repo",
            task_type=TaskType.IMPLEMENT,
            status=WorkItemStatus.QUEUED,
            node_id="node_7",
        )

        data = item.model_dump()
        assert data["id"] == "7"
        assert data["issue_number"] == 7
        assert data["task_type"] == TaskType.IMPLEMENT
        assert data["status"] == WorkItemStatus.QUEUED

    @pytest.mark.unit
    def test_work_item_json_serialization(self):
        """Test that WorkItem can be serialized to JSON."""
        item = WorkItem(
            id="8",
            issue_number=8,
            source_url="https://github.com/org/repo/issues/8",
            context_body="Test task",
            target_repo_slug="org/repo",
            task_type=TaskType.PLAN,
            status=WorkItemStatus.IN_PROGRESS,
            node_id="node_8",
        )

        json_str = item.model_dump_json()
        assert '"id":"8"' in json_str
        assert '"issue_number":8' in json_str
        assert '"task_type":"PLAN"' in json_str
        assert '"status":"agent:in-progress"' in json_str


class TestScrubSecrets:
    """Tests for scrub_secrets function."""

    @pytest.mark.unit
    def test_scrub_github_pat_classic(self):
        """Test scrubbing GitHub classic PAT format."""
        text = "Token: ghp_1234567890abcdefghijklmnopqrstuvwxyz"
        result = scrub_secrets(text)
        assert "ghp_" not in result
        assert "***REDACTED***" in result

    @pytest.mark.unit
    def test_scrub_github_app_token(self):
        """Test scrubbing GitHub App installation token format."""
        text = "App token: ghs_1234567890abcdefghijklmnopqrstuvwxyz"
        result = scrub_secrets(text)
        assert "ghs_" not in result
        assert "***REDACTED***" in result

    @pytest.mark.unit
    def test_scrub_github_oauth_token(self):
        """Test scrubbing GitHub OAuth token format."""
        text = "OAuth: gho_1234567890abcdefghijklmnopqrstuvwxyz"
        result = scrub_secrets(text)
        assert "gho_" not in result
        assert "***REDACTED***" in result

    @pytest.mark.unit
    def test_scrub_github_fine_grained_pat(self):
        """Test scrubbing GitHub fine-grained PAT format."""
        text = "Fine-grained: github_pat_22abcdefghijklmnopqrstuvwxyz"
        result = scrub_secrets(text)
        assert "github_pat_" not in result
        assert "***REDACTED***" in result

    @pytest.mark.unit
    def test_scrub_bearer_token(self):
        """Test scrubbing Bearer token format."""
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9=="
        result = scrub_secrets(text)
        assert "Bearer eyJ" not in result
        assert "***REDACTED***" in result

    @pytest.mark.unit
    def test_scrub_token_prefix(self):
        """Test scrubbing 'token' prefix format."""
        text = "Authorization: token abcdefghijklmnopqrstuvwxyz123456"
        result = scrub_secrets(text)
        assert "token abcdef" not in result
        assert "***REDACTED***" in result

    @pytest.mark.unit
    def test_scrub_openai_key(self):
        """Test scrubbing OpenAI-style API key format."""
        # The regex pattern is sk-[A-Za-z0-9]{20,} - needs 20+ alphanumeric after sk-
        text = "API Key: sk-abcdefghijklmnopqrstuvwxyz123456"
        result = scrub_secrets(text)
        assert "sk-abcdefghijklmnop" not in result
        assert "***REDACTED***" in result

    @pytest.mark.unit
    def test_scrub_zhipuai_key(self):
        """Test scrubbing ZhipuAI key format."""
        text = "ZhipuAI Key: abcdefghijklmnopqrstuvwxyz12345678.zhipu_ai_key"
        result = scrub_secrets(text)
        assert ".zhipu" not in result
        assert "***REDACTED***" in result

    @pytest.mark.unit
    def test_scrub_multiple_secrets(self):
        """Test scrubbing multiple secrets in one text."""
        text = """
        GitHub PAT: ghp_1234567890abcdefghijklmnopqrstuvwxyz
        OpenAI Key: sk-abcdefghijklmnopqrstuvwxyz123456
        Normal text here.
        """
        result = scrub_secrets(text)
        assert "ghp_" not in result
        assert "sk-abcdef" not in result
        assert "Normal text here" in result
        assert result.count("***REDACTED***") >= 2

    @pytest.mark.unit
    def test_scrub_no_secrets(self):
        """Test text without secrets passes through unchanged."""
        text = "This is normal text without any secrets."
        result = scrub_secrets(text)
        assert result == text

    @pytest.mark.unit
    def test_scrub_empty_text(self):
        """Test scrubbing empty text."""
        result = scrub_secrets("")
        assert result == ""

    @pytest.mark.unit
    def test_scrub_custom_replacement(self):
        """Test using custom replacement string."""
        text = "Token: ghp_1234567890abcdefghijklmnopqrstuvwxyz"
        result = scrub_secrets(text, replacement="[SECRET]")
        assert "ghp_" not in result
        assert "[SECRET]" in result
        assert "***REDACTED***" not in result

    @pytest.mark.unit
    def test_scrub_preserves_context(self):
        """Test that scrubbing preserves surrounding context."""
        text = "Start ghp_1234567890abcdefghijklmnopqrstuvwxyz End"
        result = scrub_secrets(text)
        assert result.startswith("Start")
        assert result.endswith("End")
        assert "***REDACTED***" in result

    @pytest.mark.unit
    def test_scrub_case_insensitive_bearer(self):
        """Test that Bearer matching is case insensitive."""
        text = "Auth: bearer some_token_value_here_123456789012"
        result = scrub_secrets(text)
        # Should match case-insensitive Bearer
        assert "***REDACTED***" in result


class TestWorkItemStatusTransitions:
    """Tests for valid status transitions."""

    @pytest.mark.unit
    def test_all_status_values_are_strings(self):
        """Test that all status values are valid strings."""
        for status in WorkItemStatus:
            assert isinstance(status.value, str)
            assert status.value.startswith("agent:")

    @pytest.mark.unit
    def test_queued_to_in_progress_transition(self):
        """Test model allows QUEUED -> IN_PROGRESS transition."""
        item = WorkItem(
            id="9",
            issue_number=9,
            source_url="https://github.com/org/repo/issues/9",
            context_body="Test",
            target_repo_slug="org/repo",
            task_type=TaskType.IMPLEMENT,
            status=WorkItemStatus.QUEUED,
            node_id="node_9",
        )
        # Simulate status update
        item = item.model_copy(update={"status": WorkItemStatus.IN_PROGRESS})
        assert item.status == WorkItemStatus.IN_PROGRESS

    @pytest.mark.unit
    def test_in_progress_to_success_transition(self):
        """Test model allows IN_PROGRESS -> SUCCESS transition."""
        item = WorkItem(
            id="10",
            issue_number=10,
            source_url="https://github.com/org/repo/issues/10",
            context_body="Test",
            target_repo_slug="org/repo",
            task_type=TaskType.IMPLEMENT,
            status=WorkItemStatus.IN_PROGRESS,
            node_id="node_10",
        )
        item = item.model_copy(update={"status": WorkItemStatus.SUCCESS})
        assert item.status == WorkItemStatus.SUCCESS

    @pytest.mark.unit
    def test_in_progress_to_error_transition(self):
        """Test model allows IN_PROGRESS -> ERROR transition."""
        item = WorkItem(
            id="11",
            issue_number=11,
            source_url="https://github.com/org/repo/issues/11",
            context_body="Test",
            target_repo_slug="org/repo",
            task_type=TaskType.IMPLEMENT,
            status=WorkItemStatus.IN_PROGRESS,
            node_id="node_11",
        )
        item = item.model_copy(update={"status": WorkItemStatus.ERROR})
        assert item.status == WorkItemStatus.ERROR

    @pytest.mark.unit
    def test_in_progress_to_infra_failure_transition(self):
        """Test model allows IN_PROGRESS -> INFRA_FAILURE transition."""
        item = WorkItem(
            id="12",
            issue_number=12,
            source_url="https://github.com/org/repo/issues/12",
            context_body="Test",
            target_repo_slug="org/repo",
            task_type=TaskType.IMPLEMENT,
            status=WorkItemStatus.IN_PROGRESS,
            node_id="node_12",
        )
        item = item.model_copy(update={"status": WorkItemStatus.INFRA_FAILURE})
        assert item.status == WorkItemStatus.INFRA_FAILURE
