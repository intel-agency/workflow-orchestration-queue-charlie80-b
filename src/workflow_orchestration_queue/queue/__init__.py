"""Queue management for workflow orchestration."""

from workflow_orchestration_queue.queue.github_queue import GitHubQueue, ITaskQueue

__all__ = ["ITaskQueue", "GitHubQueue"]
