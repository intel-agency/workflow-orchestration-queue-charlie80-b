"""
OS-APOW Sentinel Orchestrator.

Implementation of Phase 1: Story 2 & 3.

This script acts as the 'Brain' of the OS-APOW system. It:
1. Polls a GitHub repo for issues labeled 'agent:queued'.
2. Claims the task using assign-then-verify distributed locking.
3. Manages the worker lifecycle via './scripts/devcontainer-opencode.sh'.
4. Posts heartbeat comments during long-running tasks.
5. Reports progress and results back to GitHub.
"""

import asyncio
import contextlib
import logging
import os
import random
import signal
import subprocess
import sys
import uuid

import httpx

from workflow_orchestration_queue.models.work_item import (
    TaskType,
    WorkItem,
    WorkItemStatus,
)
from workflow_orchestration_queue.queue.github_queue import GitHubQueue

# --- 1. Configuration ---
# Required env vars: GITHUB_TOKEN, GITHUB_ORG, GITHUB_REPO
# Optional: SENTINEL_BOT_LOGIN (enables assign-then-verify locking)
# All other values are hardcoded with sensible defaults for MVP.
# Promote to env vars later if operational experience warrants it (see S-3).

POLL_INTERVAL = 60  # seconds between polling cycles
MAX_BACKOFF = 960  # 16 minutes max backoff on rate limits
SENTINEL_ID = f"sentinel-{uuid.uuid4().hex[:8]}"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_ORG = os.getenv("GITHUB_ORG")
GITHUB_REPO = os.getenv("GITHUB_REPO")
SHELL_BRIDGE_PATH = "./scripts/devcontainer-opencode.sh"
HEARTBEAT_INTERVAL = 300  # 5 min between heartbeat comments

# Subprocess hard timeout: safety net in case inner watchdog fails (R-8)
# Higher than run_opencode_prompt.sh HARD_CEILING_SECS (5400) to avoid racing.
SUBPROCESS_TIMEOUT = 5700  # 95 min

# Sentinel bot account name — used for assign-then-verify locking (R-2).
# Must match the GitHub account the GITHUB_TOKEN authenticates as.
SENTINEL_BOT_LOGIN = os.getenv("SENTINEL_BOT_LOGIN", "")

# Setup Structured Logging
logging.basicConfig(
    level=logging.INFO,
    format=f"%(asctime)s [%(levelname)s] {SENTINEL_ID} - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("OS-APOW-Sentinel")

# Graceful shutdown flag (R-4)
_shutdown_requested = False


# --- 2. Signal Handling (R-4) ---


def _handle_signal(signum: int, _frame: object) -> None:
    """Set shutdown flag on SIGTERM/SIGINT so the current task can finish.

    Args:
        signum: The signal number received.
        _frame: The current stack frame (unused).
    """
    global _shutdown_requested
    sig_name = signal.Signals(signum).name
    logger.info(f"Received {sig_name} — will shut down after current task finishes")
    _shutdown_requested = True


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


# --- 3. Shell Bridge Interface ---


async def run_shell_command(
    args: list[str], timeout: int | None = None
) -> subprocess.CompletedProcess[str]:
    """Invokes the local shell bridge (devcontainer-opencode.sh).

    Args:
        args: Command and arguments.
        timeout: Maximum seconds to wait. None = no limit.

    Returns:
        A CompletedProcess with the command results.
    """
    try:
        logger.info(f"Executing Bridge: {' '.join(args)}")
        process = await asyncio.create_subprocess_exec(
            *args, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )
        except TimeoutError:
            logger.warning(f"Shell command timed out after {timeout}s — killing")
            process.kill()
            stdout, stderr = await process.communicate()

            # After kill, process.returncode is set but mypy doesn't know that
            # Use -1 as the returncode for timeout case
            return subprocess.CompletedProcess(
                args=args,
                returncode=-1,
                stdout=stdout.decode().strip() if stdout else "",
                stderr=f"TIMEOUT after {timeout}s\n" + (stderr.decode().strip() if stderr else ""),
            )

        # After communicate(), returncode is guaranteed to be set
        returncode = process.returncode if process.returncode is not None else -1

        return subprocess.CompletedProcess(
            args=args,
            returncode=returncode,
            stdout=stdout.decode().strip() if stdout else "",
            stderr=stderr.decode().strip() if stderr else "",
        )
    except Exception as e:
        logger.error(f"Critical shell execution error: {str(e)}")
        raise


# --- 4. Queue (imported from workflow_orchestration_queue.queue.github_queue) ---


# --- 5. Orchestration Logic ---


class Sentinel:
    """Orchestrator that polls for and processes queued tasks."""

    def __init__(self, queue: GitHubQueue) -> None:
        """Initialize the Sentinel with a queue.

        Args:
            queue: The GitHub queue to poll for tasks.
        """
        self.queue = queue
        self._current_backoff = POLL_INTERVAL

    # --- Heartbeat coroutine (R-1) ---

    async def _heartbeat_loop(self, item: WorkItem, start_time: float) -> None:
        """Post periodic heartbeat comments while a task is running.

        Args:
            item: The work item being processed.
            start_time: The monotonic time when processing started.
        """
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            elapsed = int(asyncio.get_event_loop().time() - start_time)
            await self.queue.post_heartbeat(item, SENTINEL_ID, elapsed)

    async def process_task(self, item: WorkItem) -> None:
        """Process a single work item through the full workflow.

        Args:
            item: The work item to process.
        """
        logger.info(f"Processing Task #{item.issue_number}...")
        start_time = asyncio.get_event_loop().time()

        # Launch heartbeat as a background task (R-1)
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(item, start_time))

        try:
            # Step 1: Initialize Infrastructure
            res_up = await run_shell_command([SHELL_BRIDGE_PATH, "up"], timeout=300)
            if res_up.returncode != 0:
                err = f"❌ **Infrastructure Failure** during `up` stage:\n```\n{res_up.stderr}\n```"
                await self.queue.update_status(item, WorkItemStatus.INFRA_FAILURE, err)
                return

            # Step 2: Start Opencode Server
            res_start = await run_shell_command([SHELL_BRIDGE_PATH, "start"], timeout=120)
            if res_start.returncode != 0:
                err = f"❌ **Infrastructure Failure** starting `opencode-server`:\n```\n{res_start.stderr}\n```"
                await self.queue.update_status(item, WorkItemStatus.INFRA_FAILURE, err)
                return

            # Step 3: Trigger Agent Workflow
            workflow_map = {
                TaskType.PLAN: "create-app-plan.md",
                TaskType.IMPLEMENT: "perform-task.md",
                TaskType.BUGFIX: "recover-from-error.md",
            }
            workflow = workflow_map.get(item.task_type, "perform-task.md")
            instruction = f"Execute workflow {workflow} for context: {item.source_url}"

            # Primary bridge call with subprocess timeout safety net (R-8)
            res_prompt = await run_shell_command(
                [SHELL_BRIDGE_PATH, "prompt", instruction],
                timeout=SUBPROCESS_TIMEOUT,
            )

            # Step 4: Handle Completion
            if res_prompt.returncode == 0:
                success_msg = (
                    f"✅ **Workflow Complete**\n"
                    f"Sentinel successfully executed `{workflow}`. "
                    f"Please review Pull Requests."
                )
                await self.queue.update_status(item, WorkItemStatus.SUCCESS, success_msg)
            else:
                log_tail = (
                    res_prompt.stderr[-1500:] if res_prompt.stderr else "No error output captured."
                )
                fail_msg = f"❌ **Execution Error** during `{workflow}`:\n```\n...{log_tail}\n```"
                await self.queue.update_status(item, WorkItemStatus.ERROR, fail_msg)

        except Exception as e:
            logger.exception(f"Internal Sentinel Error on Task #{item.issue_number}")
            await self.queue.update_status(
                item,
                WorkItemStatus.INFRA_FAILURE,
                f"🚨 Sentinel encountered an unhandled exception: {str(e)}",
            )
        finally:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task

            # Environment reset between tasks — stop container but keep for fast restart
            logger.info("Resetting environment (stop)")
            await run_shell_command([SHELL_BRIDGE_PATH, "stop"], timeout=60)

    async def run_forever(self) -> None:
        """Run the main polling loop until shutdown is requested."""
        logger.info(f"Sentinel {SENTINEL_ID} entering polling loop (interval: {POLL_INTERVAL}s)")

        global _shutdown_requested

        while not _shutdown_requested:
            try:
                tasks = await self.queue.fetch_queued_tasks()
                if tasks:
                    logger.info(f"Found {len(tasks)} queued task(s).")
                    for task in tasks:
                        if _shutdown_requested:
                            break
                        if await self.queue.claim_task(task, SENTINEL_ID, SENTINEL_BOT_LOGIN):
                            await self.process_task(task)
                            break

                # Reset backoff on successful poll (I-3)
                self._current_backoff = POLL_INTERVAL

            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status in (403, 429):
                    # Jittered exponential backoff (I-3)
                    jitter = random.uniform(0, self._current_backoff * 0.1)
                    wait = min(self._current_backoff + jitter, MAX_BACKOFF)
                    logger.warning(f"Rate limited ({status}) — backing off {wait:.0f}s")
                    self._current_backoff = min(self._current_backoff * 2, MAX_BACKOFF)
                    await asyncio.sleep(wait)
                    continue
                else:
                    logger.error(f"GitHub API error: {exc}")
            except Exception as e:
                logger.error(f"Polling cycle error: {str(e)}")

            await asyncio.sleep(self._current_backoff)

        logger.info("Shutdown flag set — exiting polling loop")


# --- 6. Entry Point ---


async def _main() -> None:
    """Main entry point for the Sentinel orchestrator."""
    required = ["GITHUB_TOKEN", "GITHUB_ORG", "GITHUB_REPO"]
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        logger.error(f"Critical Error: Missing environment variables: {', '.join(missing)}")
        sys.exit(1)

    if not SENTINEL_BOT_LOGIN:
        logger.warning(
            "SENTINEL_BOT_LOGIN is not set — assign-then-verify locking is disabled. "
            "Set it to the GitHub login of the bot account for concurrency safety (R-2)."
        )

    # Type narrow - we've verified these are not None above
    token = os.getenv("GITHUB_TOKEN")
    org = os.getenv("GITHUB_ORG")
    repo = os.getenv("GITHUB_REPO")

    if token is None or org is None or repo is None:
        logger.error("Critical Error: Required environment variables became None")
        sys.exit(1)

    gh_queue = GitHubQueue(token, org, repo)
    sentinel = Sentinel(gh_queue)

    try:
        await sentinel.run_forever()
    finally:
        await gh_queue.close()
        logger.info("Sentinel shut down.")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        logger.info("Sentinel shutting down gracefully.")
