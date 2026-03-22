"""
OS-APOW GitHub Queue.

Consolidated GitHub-backed work queue used by both the Sentinel
Orchestrator and the Work Event Notifier. Implements the ITaskQueue
ABC so the provider can be swapped to Linear, Jira, etc. in the future.

See: OS-APOW Simplification Report, S-1 / S-6

Epic 1.4: Assign-then-Verify Distributed Locking
- Configurable timeouts from environment
- Enhanced API error handling (404, 403, 422)
- Retry with exponential backoff for contention
- Structured logging for observability
"""

import logging
import os
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from workflow_orchestration_queue.models.work_item import (
    TaskType,
    WorkItem,
    WorkItemStatus,
    scrub_secrets,
)

logger = logging.getLogger("OS-APOW")


# --- Configuration ---


@dataclass
class LockingConfig:
    """Configuration for distributed locking behavior.

    All values can be overridden via environment variables.

    Attributes:
        api_timeout: HTTP client timeout in seconds.
        bot_login: GitHub bot login for assignment.
        max_retry_attempts: Maximum retry attempts for contention.
        initial_backoff_ms: Initial backoff in milliseconds.
        max_backoff_ms: Maximum backoff in milliseconds.
        backoff_multiplier: Exponential backoff multiplier.
    """

    api_timeout: float = 30.0
    bot_login: str = ""
    max_retry_attempts: int = 3
    initial_backoff_ms: int = 100
    max_backoff_ms: int = 2000
    backoff_multiplier: float = 2.0

    @classmethod
    def from_env(cls) -> "LockingConfig":
        """Create configuration from environment variables.

        Environment variables:
            GITHUB_API_TIMEOUT: HTTP client timeout (default: 30.0)
            SENTINEL_BOT_LOGIN: GitHub bot login (default: "")
            LOCK_RETRY_MAX_ATTEMPTS: Max retry attempts (default: 3)
            LOCK_RETRY_INITIAL_BACKOFF_MS: Initial backoff ms (default: 100)
            LOCK_RETRY_MAX_BACKOFF_MS: Max backoff ms (default: 2000)
            LOCK_RETRY_BACKOFF_MULTIPLIER: Backoff multiplier (default: 2.0)

        Returns:
            LockingConfig with values from environment or defaults.
        """
        return cls(
            api_timeout=float(os.getenv("GITHUB_API_TIMEOUT", "30.0")),
            bot_login=os.getenv("SENTINEL_BOT_LOGIN", ""),
            max_retry_attempts=int(os.getenv("LOCK_RETRY_MAX_ATTEMPTS", "3")),
            initial_backoff_ms=int(os.getenv("LOCK_RETRY_INITIAL_BACKOFF_MS", "100")),
            max_backoff_ms=int(os.getenv("LOCK_RETRY_MAX_BACKOFF_MS", "2000")),
            backoff_multiplier=float(os.getenv("LOCK_RETRY_BACKOFF_MULTIPLIER", "2.0")),
        )


# --- Exceptions ---


class LockAcquisitionError(Exception):
    """Base exception for lock acquisition failures."""

    def __init__(self, message: str, issue_number: int, **context: Any) -> None:
        """Initialize the exception.

        Args:
            message: Error message.
            issue_number: The issue number that failed.
            **context: Additional context for logging.
        """
        super().__init__(message)
        self.issue_number = issue_number
        self.context = context


class AssignmentError(LockAcquisitionError):
    """Failed to assign bot to issue."""

    pass


class VerificationError(LockAcquisitionError):
    """Failed to verify assignment after API call."""

    pass


class ContentionError(LockAcquisitionError):
    """Another worker won the race to claim the task."""

    pass


# --- Abstract Interface (kept per S-1 for future provider swapping) ---


class ITaskQueue(ABC):
    """Interface for the Work Queue (e.g., GH Issues, Linear, Jira, etc.)."""

    @abstractmethod
    async def add_to_queue(self, item: WorkItem) -> bool:
        """Add a work item to the queue.

        Args:
            item: The work item to add.

        Returns:
            True if the item was successfully added, False otherwise.
        """
        pass

    @abstractmethod
    async def fetch_queued_tasks(self) -> list[WorkItem]:
        """Fetch all queued tasks from the queue.

        Returns:
            A list of work items that are currently queued.
        """
        pass

    @abstractmethod
    async def update_status(
        self, item: WorkItem, status: WorkItemStatus, comment: str | None = None
    ) -> None:
        """Update the status of a work item.

        Args:
            item: The work item to update.
            status: The new status to set.
            comment: Optional comment to add with the status update.
        """
        pass


# --- Concrete Implementation: GitHub Issues ---


class GitHubQueue(ITaskQueue):
    """GitHub-backed work queue with connection pooling.

    Used by both the Sentinel Orchestrator and the Work Event Notifier.
    The sentinel passes org/repo for polling; the notifier only needs a
    token since it derives the repo from the webhook payload.

    Attributes:
        config: Locking configuration for distributed locking behavior.
    """

    def __init__(
        self,
        token: str,
        org: str = "",
        repo: str = "",
        config: LockingConfig | None = None,
    ) -> None:
        """Initialize the GitHub queue.

        Args:
            token: GitHub personal access token.
            org: GitHub organization name.
            repo: GitHub repository name.
            config: Optional locking configuration. If not provided,
                defaults will be loaded from environment variables.
        """
        self.token = token
        self.org = org
        self.repo = repo
        self.config = config or LockingConfig.from_env()
        self.headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }
        self._client: httpx.AsyncClient | None = httpx.AsyncClient(
            headers=self.headers,
            timeout=self.config.api_timeout,
        )

    async def close(self) -> None:
        """Release the connection pool. Call during graceful shutdown."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _repo_api_url(self, repo_slug: str) -> str:
        """Build the GitHub API URL for a repository.

        Args:
            repo_slug: The repository slug (org/repo format).

        Returns:
            The full GitHub API URL for the repository.
        """
        return f"https://api.github.com/repos/{repo_slug}"

    # --- ITaskQueue implementation ---

    async def add_to_queue(self, item: WorkItem) -> bool:
        """Add the agent:queued label to a GitHub issue.

        Args:
            item: The work item to queue.

        Returns:
            True if the item was successfully queued, False otherwise.
        """
        if self._client is None:
            logger.error("HTTP client is closed")
            return False

        url = f"{self._repo_api_url(item.target_repo_slug)}/issues/{item.issue_number}/labels"
        resp = await self._client.post(url, json={"labels": [WorkItemStatus.QUEUED.value]})
        if resp.status_code in (200, 201):
            logger.info(f"Queued issue #{item.issue_number} ({item.task_type.value})")
            return True
        logger.error(f"Failed to queue #{item.issue_number}: {resp.status_code}")
        return False

    async def fetch_queued_tasks(self) -> list[WorkItem]:
        """Query GitHub for issues labeled 'agent:queued' in the configured repo.

        Note: Cross-repo org-wide polling via the Search API is planned
        for a future phase. Currently requires org and repo to be set.

        Returns:
            A list of work items that are currently queued.

        Raises:
            httpx.HTTPStatusError: If a rate limit error (403/429) is encountered.
        """
        if self._client is None:
            logger.error("HTTP client is closed")
            return []

        if not self.org or not self.repo:
            logger.warning("fetch_queued_tasks requires org and repo to be set")
            return []

        url = f"{self._repo_api_url(f'{self.org}/{self.repo}')}/issues"
        params = {"labels": WorkItemStatus.QUEUED.value, "state": "open"}

        response = await self._client.get(url, params=params)

        if response.status_code in (403, 429):
            # Propagate rate-limit errors so the sentinel's backoff logic fires
            response.raise_for_status()

        if response.status_code != 200:
            logger.error(f"GitHub API error: {response.status_code} {response.text[:200]}")
            return []

        issues = response.json()

        work_items = []
        for issue in issues:
            labels = [label["name"] for label in issue.get("labels", [])]
            task_type = TaskType.IMPLEMENT
            if "agent:plan" in labels or "[Plan]" in issue.get("title", ""):
                task_type = TaskType.PLAN
            elif "bug" in labels:
                task_type = TaskType.BUGFIX

            repo_slug = "/".join(issue["html_url"].split("/")[3:5])

            work_items.append(
                WorkItem(
                    id=str(issue["id"]),
                    issue_number=issue["number"],
                    source_url=issue["html_url"],
                    context_body=issue.get("body") or "",
                    target_repo_slug=repo_slug,
                    task_type=task_type,
                    status=WorkItemStatus.QUEUED,
                    node_id=issue["node_id"],
                )
            )
        return work_items

    async def update_status(
        self, item: WorkItem, status: WorkItemStatus, comment: str | None = None
    ) -> None:
        """Finalize the task state on GitHub with terminal labels and logs.

        Args:
            item: The work item to update.
            status: The new status to set.
            comment: Optional comment to add with the status update.
        """
        if self._client is None:
            logger.error("HTTP client is closed")
            return

        base = self._repo_api_url(item.target_repo_slug)
        url_labels = f"{base}/issues/{item.issue_number}/labels"

        resp = await self._client.delete(f"{url_labels}/{WorkItemStatus.IN_PROGRESS.value}")
        if resp.status_code not in (200, 204, 404, 410):
            logger.error(f"Label cleanup failed: {resp.status_code}")

        await self._client.post(url_labels, json={"labels": [status.value]})

        if comment:
            safe_comment = scrub_secrets(comment)
            comment_url = f"{base}/issues/{item.issue_number}/comments"
            await self._client.post(comment_url, json={"body": safe_comment})

    # --- Sentinel-specific methods ---

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff with jitter.

        Args:
            attempt: The current attempt number (0-indexed).

        Returns:
            Backoff time in seconds.
        """
        # Calculate exponential backoff
        backoff_ms = self.config.initial_backoff_ms * (self.config.backoff_multiplier**attempt)
        # Cap at max backoff
        backoff_ms = min(backoff_ms, self.config.max_backoff_ms)
        # Add jitter (0-25% of backoff time)
        jitter_ms = backoff_ms * random.random() * 0.25  # noqa: S311
        return (backoff_ms + jitter_ms) / 1000.0

    def _log_lock_event(
        self,
        event: str,
        issue_number: int,
        level: int = logging.INFO,
        **context: Any,
    ) -> None:
        """Log a structured lock event.

        Args:
            event: The event name (e.g., 'assignment_attempt', 'lock_acquired').
            issue_number: The issue number.
            level: Log level (default: INFO).
            **context: Additional context for structured logging.
        """
        context_str = " ".join(f"{k}={v}" for k, v in context.items())
        logger.log(level, f"[{event}] issue={issue_number} {context_str}")

    async def claim_task(self, item: WorkItem, sentinel_id: str, bot_login: str = "") -> bool:
        """Claim a task using assign-then-verify distributed locking.

        Steps:
          1. Attempt to assign bot_login to the issue.
          2. Re-fetch the issue to verify we are the assignee.
          3. Only then update labels and post the claim comment.

        This method performs a single claim attempt without retry logic.
        For automatic retries on contention, use claim_task_with_retry().

        Args:
            item: The work item to claim.
            sentinel_id: The identifier of the sentinel claiming the task.
            bot_login: The GitHub login of the bot account. If empty,
                falls back to config.bot_login.

        Returns:
            True if the task was successfully claimed, False otherwise.

        Raises:
            AssignmentError: If assignment fails due to API error (404, 403, 422).
            VerificationError: If verification request fails.
            ContentionError: If another worker won the race.
        """
        if self._client is None:
            self._log_lock_event("client_closed", item.issue_number, level=logging.ERROR)
            return False

        # Use provided bot_login or fall back to config
        effective_bot_login = bot_login or self.config.bot_login

        base = self._repo_api_url(item.target_repo_slug)
        url_issue = f"{base}/issues/{item.issue_number}"

        # Step 1: Attempt assignment
        if effective_bot_login:
            self._log_lock_event(
                "assignment_attempt",
                item.issue_number,
                bot=effective_bot_login,
            )

            try:
                resp = await self._client.post(
                    f"{url_issue}/assignees",
                    json={"assignees": [effective_bot_login]},
                )
            except httpx.HTTPError as exc:
                self._log_lock_event(
                    "assignment_network_error",
                    item.issue_number,
                    level=logging.ERROR,
                    error=str(exc),
                )
                raise AssignmentError(
                    f"Network error during assignment: {exc}",
                    item.issue_number,
                    bot_login=effective_bot_login,
                ) from exc

            # Handle specific error codes
            if resp.status_code == 404:
                self._log_lock_event(
                    "assignment_not_found",
                    item.issue_number,
                    level=logging.ERROR,
                    status=404,
                )
                raise AssignmentError(
                    f"Issue #{item.issue_number} not found",
                    item.issue_number,
                    status_code=404,
                )

            if resp.status_code == 403:
                self._log_lock_event(
                    "assignment_forbidden",
                    item.issue_number,
                    level=logging.ERROR,
                    status=403,
                )
                raise AssignmentError(
                    f"Permission denied to assign to issue #{item.issue_number}",
                    item.issue_number,
                    status_code=403,
                )

            if resp.status_code == 422:
                self._log_lock_event(
                    "assignment_validation_error",
                    item.issue_number,
                    level=logging.ERROR,
                    status=422,
                    response=resp.text[:200],
                )
                raise AssignmentError(
                    f"Validation error assigning to issue #{item.issue_number}",
                    item.issue_number,
                    status_code=422,
                    response=resp.text[:200],
                )

            if resp.status_code not in (200, 201):
                self._log_lock_event(
                    "assignment_failed",
                    item.issue_number,
                    level=logging.WARNING,
                    status=resp.status_code,
                )
                return False

            self._log_lock_event(
                "assignment_success",
                item.issue_number,
                bot=effective_bot_login,
            )

            # Step 2: Re-fetch and verify assignee
            try:
                verify_resp = await self._client.get(url_issue)
            except httpx.HTTPError as exc:
                self._log_lock_event(
                    "verification_network_error",
                    item.issue_number,
                    level=logging.ERROR,
                    error=str(exc),
                )
                raise VerificationError(
                    f"Network error during verification: {exc}",
                    item.issue_number,
                ) from exc

            if verify_resp.status_code == 200:
                assignees = [a["login"] for a in verify_resp.json().get("assignees", [])]
                if effective_bot_login not in assignees:
                    self._log_lock_event(
                        "lock_contended",
                        item.issue_number,
                        level=logging.WARNING,
                        expected=effective_bot_login,
                        actual=assignees,
                    )
                    raise ContentionError(
                        f"Lost race on #{item.issue_number}",
                        item.issue_number,
                        expected_assignee=effective_bot_login,
                        actual_assignees=assignees,
                    )
                self._log_lock_event(
                    "verification_success",
                    item.issue_number,
                    assignee=effective_bot_login,
                )
            else:
                self._log_lock_event(
                    "verification_failed",
                    item.issue_number,
                    level=logging.WARNING,
                    status=verify_resp.status_code,
                )
                raise VerificationError(
                    f"Could not verify assignment for #{item.issue_number}: "
                    f"status {verify_resp.status_code}",
                    item.issue_number,
                    status_code=verify_resp.status_code,
                )

        # Step 3: Update labels
        url_labels = f"{url_issue}/labels"
        resp = await self._client.delete(f"{url_labels}/{WorkItemStatus.QUEUED.value}")
        if resp.status_code not in (200, 204, 404, 410):
            self._log_lock_event(
                "label_removal_failed",
                item.issue_number,
                level=logging.ERROR,
                status=resp.status_code,
            )
            return False

        await self._client.post(
            url_labels,
            json={"labels": [WorkItemStatus.IN_PROGRESS.value]},
        )

        # Step 4: Post claim comment
        comment_url = f"{url_issue}/comments"
        msg = (
            f"🚀 **Sentinel {sentinel_id}** has claimed this task.\n"
            f"- **Start Time:** {datetime.now(UTC).isoformat()}\n"
            f"- **Environment:** `devcontainer-opencode.sh` initializing..."
        )
        await self._client.post(comment_url, json={"body": msg})

        self._log_lock_event(
            "lock_acquired",
            item.issue_number,
            sentinel=sentinel_id,
        )
        return True

    async def claim_task_with_retry(
        self,
        item: WorkItem,
        sentinel_id: str,
        bot_login: str = "",
    ) -> bool:
        """Claim a task with automatic retry on contention.

        Uses exponential backoff with jitter for retries. Only retries
        on ContentionError (another worker won the race). Other errors
        (404, 403, 422, network errors) are not retried.

        Args:
            item: The work item to claim.
            sentinel_id: The identifier of the sentinel claiming the task.
            bot_login: The GitHub login of the bot account. If empty,
                falls back to config.bot_login.

        Returns:
            True if the task was successfully claimed, False if all
            retry attempts were exhausted due to contention.
        """
        effective_bot_login = bot_login or self.config.bot_login

        for attempt in range(self.config.max_retry_attempts):
            self._log_lock_event(
                "claim_attempt",
                item.issue_number,
                attempt=attempt + 1,
                max_attempts=self.config.max_retry_attempts,
            )

            try:
                result = await self.claim_task(item, sentinel_id, effective_bot_login)
                # Return result directly - True if claimed, False if non-exception failure
                return result

            except ContentionError as exc:
                self._log_lock_event(
                    "claim_contended",
                    item.issue_number,
                    level=logging.WARNING,
                    attempt=attempt + 1,
                    actual_assignees=exc.context.get("actual_assignees", []),
                )

                # Check if we have more attempts
                if attempt + 1 < self.config.max_retry_attempts:
                    backoff = self._calculate_backoff(attempt)
                    self._log_lock_event(
                        "claim_retry",
                        item.issue_number,
                        level=logging.INFO,
                        backoff_ms=int(backoff * 1000),
                    )
                    import asyncio

                    await asyncio.sleep(backoff)
                else:
                    self._log_lock_event(
                        "claim_exhausted",
                        item.issue_number,
                        level=logging.WARNING,
                        attempts=self.config.max_retry_attempts,
                    )
                    return False

            except (AssignmentError, VerificationError):
                # Don't retry on these errors - they indicate permanent failures
                raise

        return False

    async def post_heartbeat(self, item: WorkItem, sentinel_id: str, elapsed_secs: int) -> None:
        """Post a heartbeat comment to keep observers informed.

        Args:
            item: The work item being processed.
            sentinel_id: The identifier of the sentinel processing the task.
            elapsed_secs: The number of seconds elapsed since processing started.
        """
        if self._client is None:
            logger.warning("HTTP client is closed, cannot post heartbeat")
            return

        base = self._repo_api_url(item.target_repo_slug)
        comment_url = f"{base}/issues/{item.issue_number}/comments"
        minutes = elapsed_secs // 60
        msg = (
            f"💓 **Heartbeat** — Sentinel {sentinel_id} still working.\n"
            f"- **Elapsed:** {minutes}m\n"
            f"- **Timestamp:** {datetime.now(UTC).isoformat()}"
        )
        try:
            await self._client.post(comment_url, json={"body": msg})
        except Exception as exc:
            logger.warning(f"Heartbeat post failed: {exc}")
