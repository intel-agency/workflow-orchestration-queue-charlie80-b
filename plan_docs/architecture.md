# Architecture: workflow-orchestration-queue

**Project:** workflow-orchestration-queue  
**Purpose:** Headless agentic orchestration platform  
**Last Updated:** 2026-03-21

---

## Executive Summary

workflow-orchestration-queue represents a paradigm shift from **Interactive AI Coding** to **Headless Agentic Orchestration**. Traditional AI developer tools require a human-in-the-loop to navigate files, provide context, and trigger executions. This system replaces that manual overhead with persistent, event-driven infrastructure that transforms GitHub Issues into "Execution Orders" autonomously fulfilled by specialized AI agents.

The system is **Self-Bootstrapping**: the initial deployment is seeded from a template clone, and once the "Sentinel" is active, the system uses its own orchestration capabilities to refine its components.

---

## System Architecture: The Four Pillars

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         workflow-orchestration-queue                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌──────────────┐     ┌──────────────┐     ┌──────────────┐               │
│   │   THE EAR    │────▶│  THE STATE   │◀────│  THE BRAIN   │               │
│   │  (Notifier)  │     │  (Queue)     │     │  (Sentinel)  │               │
│   │   FastAPI    │     │ GitHub Issues│     │   Python     │               │
│   └──────────────┘     └──────────────┘     └──────┬───────┘               │
│           │                                          │                       │
│           │                                          ▼                       │
│           │                                 ┌──────────────┐               │
│           │                                 │  THE HANDS   │               │
│           │                                 │   (Worker)   │               │
│           │                                 │  DevContainer│               │
│           │                                 └──────────────┘               │
│           │                                          │                       │
│           ▼                                          ▼                       │
│   ┌──────────────────────────────────────────────────────────────┐         │
│   │                    GitHub REST API                            │         │
│   │   (Issues, Labels, Comments, Assignees, Pull Requests)        │         │
│   └──────────────────────────────────────────────────────────────┘         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Component Details

### 1. The Ear (Work Event Notifier)

**Technology:** Python 3.12, FastAPI, Pydantic, uvicorn  
**File:** `src/notifier_service.py`

The system's primary gateway for external stimuli and asynchronous triggers.

**Responsibilities:**
- **Secure Webhook Ingestion:** Hardened endpoint receives `issues`, `issue_comment`, and `pull_request` events
- **Cryptographic Verification:** HMAC SHA256 validation against `WEBHOOK_SECRET` prevents spoofing and prompt injection
- **Intelligent Event Triage:** Parses issue body and labels, maps payloads to unified `WorkItem` object
- **Manifest Generation:** Creates structured JSON manifest for machine-readable state sharing
- **Queue Initialization:** Applies `agent:queued` label to trigger Sentinel processing

**Endpoints:**
- `POST /webhooks/github` — Primary webhook receiver
- `GET /health` — Health check endpoint
- `GET /docs` — Auto-generated OpenAPI/Swagger documentation

---

### 2. The State (Work Queue)

**Implementation:** GitHub Issues, Labels, Milestones  
**Philosophy:** "Markdown as a Database"

Using GitHub as the persistence layer provides world-class audit logs, transparent versioning, and an out-of-the-box UI for human supervision.

**State Machine (Label Logic):**

```
                    ┌─────────────────┐
                    │  agent:queued   │ ◀── New work item detected
                    └────────┬────────┘
                             │
                    Sentinel claims task
                             │
                             ▼
                    ┌─────────────────┐
                    │ agent:in-progress│
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
    ┌──────────────┐ ┌──────────────┐ ┌───────────────────┐
    │agent:success │ │ agent:error  │ │agent:infra-failure│
    └──────────────┘ └──────────────┘ └───────────────────┘
```

**Special States:**
- `agent:reconciling` — Stale tasks identified for recovery
- `agent:stalled-budget` — Daily cost threshold exceeded (Phase 3)

**Concurrency Control:**
Uses GitHub "Assignees" as a distributed lock semaphore with **assign-then-verify** pattern:
1. Attempt to assign `SENTINEL_BOT_LOGIN` to the issue
2. Re-fetch the issue
3. Verify `SENTINEL_BOT_LOGIN` appears in assignees
4. Only then proceed with label updates

---

### 3. The Brain (Sentinel Orchestrator)

**Technology:** Python (Async), Docker CLI  
**File:** `src/orchestrator_sentinel.py`

The persistent supervisor managing Worker lifecycle and mapping intent to shell commands.

**Lifecycle:**

1. **Polling Discovery:** Every 60 seconds (configurable), scans for `agent:queued` issues
   - Uses GitHub Issues API: `GET /repos/{owner}/{repo}/issues?labels=agent:queued&state=open`
   - Applies jittered exponential backoff on rate-limit (403/429)
   - Max backoff: 960s (16 minutes)

2. **Auth Synchronization:** Runs `scripts/gh-auth.ps1` before execution

3. **Shell-Bridge Protocol:** Manages Worker via three commands:
   - `./scripts/devcontainer-opencode.sh up` — Provision network and volumes
   - `./scripts/devcontainer-opencode.sh start` — Launch opencode-server
   - `./scripts/devcontainer-opencode.sh prompt "{workflow}"` — Dispatch task

4. **Workflow Mapping:** Translates issue type to specific prompt string

5. **Telemetry:** Captures stdout to local logs, posts heartbeat comments every 5 minutes

6. **Environment Reset:** Stops worker container between tasks (configurable: `none`/`stop`/`down`)

7. **Graceful Shutdown:** Handles `SIGTERM`/`SIGINT`, finishes current task, exits cleanly

---

### 4. The Hands (Opencode Worker)

**Technology:** opencode-server CLI, LLM (GLM-5 / Claude)  
**Environment:** Docker DevContainer from template

The execution layer where actual coding happens.

**Worker Capabilities:**
- **Contextual Awareness:** Accesses project structure, runs `scripts/update-remote-indices.ps1`
- **Instructional Logic:** Reads/executes markdown workflow modules from `/local_ai_instruction_modules/`
- **Verification:** Runs local test suites before submitting PR

**Key Principle:** "Logic-as-Markdown" — workflows are updated via PR without changing Python code.

---

## Data Flow: The Happy Path

```
1. User opens GitHub Issue with [Plan] template
                    │
                    ▼
2. GitHub Webhook hits Notifier (FastAPI)
                    │
                    ▼
3. Notifier verifies HMAC, confirms title pattern, adds agent:queued label
                    │
                    ▼
4. Sentinel poller detects new label
                    │
                    ▼
5. Sentinel claims task (assign-then-verify), updates to agent:in-progress
                    │
                    ▼
6. Sentinel syncs repo: git clone/pull into managed workspace
                    │
                    ▼
7. Sentinel executes: devcontainer-opencode.sh up
                    │
                    ▼
8. Sentinel dispatches: devcontainer-opencode.sh prompt "Run workflow: ..."
                    │
                    ▼
9. Worker (Opencode) reads issue, analyzes codebase, creates sub-tasks
                    │
                    ▼
10. Worker posts "Execution Complete" comment
                    │
                    ▼
11. Sentinel detects exit, removes in-progress, adds agent:success
```

---

## Key Architectural Decisions (ADRs)

### ADR 07: Standardized Shell-Bridge Execution

**Decision:** Orchestrator interacts with agentic environment *exclusively* via `./scripts/devcontainer-opencode.sh`

**Rationale:** Existing shell infrastructure handles complex Docker logic (volumes, SSH-agent, port mapping). Re-implementing in Python creates maintenance burden and configuration drift.

**Consequence:** Python code stays lightweight (logic/state), Shell handles "heavy lifting" (infra). Clear separation of concerns.

---

### ADR 08: Polling-First Resiliency Model

**Decision:** Sentinel uses polling as primary discovery; Webhooks are an "optimization"

**Rationale:** Webhooks are "fire and forget." If server is down during an event, that event is lost. Polling ensures "State Reconciliation" on every restart.

**Consequence:** System is inherently self-healing and resilient against downtime/network partitions.

---

### ADR 09: Provider-Agnostic Interface Layer

**Decision:** All queue interactions abstracted behind `ITaskQueue` interface (Strategy Pattern)

**Rationale:** Phase 1 targets GitHub, but architecture supports "Ticket Provider Swapping" (Linear, Notion, SQL queues) without rewriting Orchestrator dispatch logic.

**Interface Methods:**
- `fetch_queued_items()`
- `claim_task(id, sentinel_id)`
- `update_progress(id, log_line)`
- `finish_task(id, artifacts)`

---

## Security Architecture

### Network Isolation
- Worker containers run in dedicated Docker network
- Cannot access host network or local subnet
- Prevents lateral movement and infrastructure probing

### Credential Management
- Sentinel manages GitHub App Installation Token
- Token passed to Worker via temporary env var
- Destroyed immediately when session ends

### Credential Scrubbing
All log output passes through `scrub_secrets()` regex utility:
- Strips: `ghp_*`, `ghs_*`, `gho_*`, `github_pat_*`, `Bearer`, `sk-*`, ZhipuAI keys
- Produces sanitized log for GitHub visibility
- Raw log retained locally for forensics

### Resource Constraints
- Workers capped at 2 CPUs, 4GB RAM
- Prevents rogue agent from causing DoS on host

---

## Project Structure

```
workflow-orchestration-queue/
├── pyproject.toml                # uv dependencies and metadata
├── uv.lock                       # Deterministic lockfile
├── src/
│   ├── notifier_service.py       # FastAPI webhook receiver
│   ├── orchestrator_sentinel.py  # Background polling daemon
│   ├── models/
│   │   ├── work_item.py          # Unified WorkItem, TaskType, WorkItemStatus
│   │   └── github_events.py      # GitHub webhook payload schemas
│   └── queue/
│       └── github_queue.py       # ITaskQueue ABC + GitHubQueue implementation
├── scripts/
│   ├── devcontainer-opencode.sh  # Core shell bridge
│   ├── gh-auth.ps1               # GitHub auth sync
│   └── update-remote-indices.ps1 # Vector index sync
├── local_ai_instruction_modules/ # Markdown workflow logic
│   ├── create-app-plan.md
│   ├── perform-task.md
│   └── analyze-bug.md
└── docs/                         # Architecture and user docs
```

---

## Self-Bootstrapping Lifecycle

```
Phase 0 (Manual):
  Clone template → Seed plan docs → Initialize DevContainer

Phase 1 (Manual Launch):
  Run devcontainer-opencode.sh up
  Run project-setup workflow

Phase 2 (Handover):
  Start sentinel.py service on host
  From here: interact only via GitHub issues

Phase 3 (Autonomous):
  AI builds remaining features by picking up its own task tickets
```

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| GitHub API Rate Limiting | High | Use GitHub App tokens (5,000 req/hr); implement local caching; long-poll intervals |
| LLM Looping/Hallucination | High | Max steps timeout; Cost Guardrails (Story 6); Retries counter with stall threshold |
| Concurrency Collisions | Medium | Assign-then-verify pattern; GitHub Assignees as distributed lock |
| Container Drift | Medium | Stop worker between tasks; configurable reset modes |
| Security Injection | Medium | HMAC signature validation; no host .env access except explicit injection |
| Long-Running Tasks | Medium | Heartbeat comments every 5 minutes; subprocess timeout safety net |

---

## Future Directions (Phase 3+)

- Hierarchical Task Delegation (Architect Sub-Agent)
- Self-Healing Reconciliation Loop
- Cross-Repo Org-Wide Polling via Search API
- Cost Guardrails with Budget Monitoring
- PR Review Feedback Loop (automatic re-queue on "Request Changes")
