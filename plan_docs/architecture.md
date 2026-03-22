# OS-APOW Architecture Document

**Project:** workflow-orchestration-queue (OS-APOW)
**Generated:** 2026-03-22
**Status:** Planning

---

## Executive Summary

OS-APOW transforms GitHub Issues into autonomous AI-driven development tasks through a **4-pillar architecture**: Ear (Notifier), State (Queue), Brain (Sentinel), and Hands (Worker). The system is designed for **self-bootstrapping** — once seeded, the AI manages its own evolution.

---

## System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         OS-APOW SYSTEM ARCHITECTURE                          │
└─────────────────────────────────────────────────────────────────────────────┘

                    ┌──────────────────┐
                    │   GitHub Issues  │
                    │  (State Store)   │
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
    ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
    │   THE EAR   │  │  THE STATE  │  │  THE BRAIN  │
    │  (Notifier) │  │   (Queue)   │  │ (Sentinel)  │
    │   FastAPI   │  │   Labels    │  │   Poller    │
    └──────┬──────┘  └─────────────┘  └──────┬──────┘
           │                                  │
           │ Webhook Events                   │ Shell Bridge
           ▼                                  ▼
    ┌─────────────┐                  ┌─────────────┐
    │   Triage    │                  │   THE HANDS │
    │   Queue     │─────────────────▶│   (Worker)  │
    └─────────────┘   Claim & Exec   │  DevContainer│
                                       └─────────────┘
```

---

## The Four Pillars

### 1. The Ear (Work Event Notifier)

**Technology:** Python 3.12+, FastAPI, Pydantic

**Responsibilities:**
- Secure webhook ingestion via `/webhooks/github` endpoint
- HMAC SHA256 signature validation (X-Hub-Signature-256)
- Intelligent event triage and WorkItem manifest generation
- Queue initialization via `agent:queued` label application

**Key Security:**
- Rejects requests with invalid/missing signatures (401 Unauthorized)
- Responds within 10-second GitHub timeout (202 Accepted)

**Implementation:** `src/notifier_service.py`

---

### 2. The State (Work Queue)

**Philosophy:** "Markdown as a Database"

**Implementation:** GitHub Issues, Labels, Milestones

**State Machine (Label Logic):**

```
┌──────────────┐     Claim      ┌──────────────┐     Success    ┌──────────────┐
│ agent:queued │ ──────────────▶│agent:in-     │ ──────────────▶│agent:success │
└──────────────┘                │  progress    │                └──────────────┘
                                └──────┬───────┘
                                       │ Error
                                       ▼
                                ┌──────────────┐
                                │ agent:error  │
                                └──────────────┘
```

**Additional States:**
- `agent:infra-failure` - Container/build failures
- `agent:stalled-budget` - Cost limit exceeded
- `agent:reconciling` - Stale task recovery

**Concurrency Control:**
- Uses GitHub Assignees as distributed lock
- **Assign-then-verify pattern** prevents race conditions:
  1. Attempt to assign `SENTINEL_BOT_LOGIN` to issue
  2. Re-fetch the issue
  3. Verify assignment before proceeding
  4. If verification fails, abort gracefully

---

### 3. The Brain (Sentinel Orchestrator)

**Technology:** Python (Async Background Service), PowerShell, Docker CLI

**Responsibilities:**
- Resilient polling with jittered exponential backoff
- Task claiming via assign-then-verify pattern
- Shell-bridge dispatch to worker container
- Status feedback (heartbeat comments every 5 minutes)
- Graceful shutdown on SIGTERM/SIGINT

**Polling Strategy:**
- Primary: Single-repo GitHub Issues API
  - `GET /repos/{owner}/{repo}/issues?labels=agent:queued&state=open`
- Future: Cross-repo org-wide polling via Search API

**Backoff Implementation:**
```
wait = min(current_backoff + random(0, 0.1 * current_backoff), MAX_BACKOFF)
```
- Default `MAX_BACKOFF`: 960s (16 min)
- Reset to `POLL_INTERVAL` on successful poll

**Shell-Bridge Protocol:**
1. `./scripts/devcontainer-opencode.sh up` - Provision environment
2. `./scripts/devcontainer-opencode.sh start` - Start opencode server
3. `./scripts/devcontainer-opencode.sh prompt "{workflow}"` - Execute task
4. `./scripts/devcontainer-opencode.sh stop` - Reset between tasks

**Implementation:** `src/orchestrator_sentinel.py`

---

### 4. The Hands (Opencode Worker)

**Technology:** opencode CLI, LLM (GLM-5)

**Environment:** Docker DevContainer with:
- Python 3.12+
- Node.js 24.14.0 LTS
- Bun 1.3.10
- uv 0.10.9

**Capabilities:**
- Contextual awareness via vector-indexed codebase
- Markdown-based instruction execution from `local_ai_instruction_modules/`
- Local test suite verification before PR submission

**Resource Constraints:**
- 2 CPUs
- 4GB RAM
- Network isolation (dedicated Docker network)

---

## Key Architectural Decisions (ADRs)

### ADR 07: Shell-Bridge Execution

**Decision:** Orchestrator interacts with worker exclusively via `./scripts/devcontainer-opencode.sh`

**Rationale:** 
- Reuses existing Docker logic (volume mounts, SSH-agent forwarding, port mapping)
- Guarantees environment parity between AI and human developers
- Prevents "Configuration Drift"

**Consequence:** Python code stays lightweight; shell scripts handle infra complexity

---

### ADR 08: Polling-First Resiliency

**Decision:** Polling is primary discovery; webhooks are optimization

**Rationale:**
- Webhooks are "fire and forget" — lost if server is down
- Polling enables state reconciliation on restart
- Self-healing against network partitions

---

### ADR 09: Provider-Agnostic Interface

**Decision:** Queue interactions abstracted behind `ITaskQueue` interface

**Methods:**
- `fetch_queued()`
- `claim_task(id, sentinel_id)`
- `update_progress(id, log_line)`
- `finish_task(id, artifacts)`

**Rationale:** Enables future support for Linear, Notion, or SQL queues

---

## Data Flow (Happy Path)

```
1. User opens Issue with [Application Plan] template
           │
           ▼
2. GitHub Webhook → Notifier (FastAPI)
           │
           ▼
3. Notifier validates signature, applies agent:queued label
           │
           ▼
4. Sentinel poller detects queued issue
           │
           ▼
5. Sentinel claims via assign-then-verify pattern
           │
           ▼
6. Sentinel runs devcontainer-opencode.sh up
           │
           ▼
7. Sentinel dispatches prompt to Worker
           │
           ▼
8. Worker executes, creates PR, posts comment
           │
           ▼
9. Sentinel detects exit, updates label to agent:success
```

---

## Security Architecture

### Network Isolation

```
┌─────────────────────────────────────────────────────┐
│                    Host Machine                      │
│  ┌─────────────────────────────────────────────┐   │
│  │            Sentinel Service                  │   │
│  │         (Polling, Dispatch)                  │   │
│  └────────────────────┬────────────────────────┘   │
│                       │ Shell Bridge                │
│  ┌────────────────────▼────────────────────────┐   │
│  │         Isolated Docker Network              │   │
│  │  ┌─────────────────────────────────────┐    │   │
│  │  │         Worker Container             │    │   │
│  │  │    (No access to host subnet)        │    │   │
│  │  └─────────────────────────────────────┘    │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

### Credential Management

| Layer | Implementation |
|-------|----------------|
| **Injection** | Temporary env vars passed to container |
| **Destruction** | Vars destroyed on container exit |
| **Scrubbing** | Regex-based sanitization before GitHub posts |

**Patterns Scrubbed:**
- GitHub PATs: `ghp_*`, `ghs_*`, `gho_*`, `github_pat_*`
- Bearer tokens: `Bearer ...`
- API keys: `sk-*`
- ZhipuAI keys

---

## Self-Bootstrapping Lifecycle

```
Stage 0 (Seeding)
└── Manual clone of template repo + plan docs

Stage 1 (Manual Launch)
└── Developer runs devcontainer-opencode.sh up

Stage 2 (Project Setup)
└── Agent configures env vars, indexes codebase

Stage 3 (Handover)
└── Sentinel service started → AI takes over
    └── Phase 2 & 3 built autonomously
```

---

## Cross-Cutting Concerns

### Unified Data Model

All Pydantic models defined in single module: `src/models/work_item.py`

**Shared between Sentinel and Notifier:**
- `WorkItem` - Task representation
- `TaskType` - PLAN, IMPLEMENT, etc.
- `WorkItemStatus` - Enum mapping to GitHub labels
- `scrub_secrets()` - Credential sanitization utility

### Graceful Shutdown

- Handles `SIGTERM` and `SIGINT` signals
- Sets `_shutdown_requested` flag
- Completes current task before exit
- Closes `httpx` connection pool

### Subprocess Timeout

- Prompt commands: 5700s (95 min) timeout
- Higher than inner watchdog (5400s) to avoid racing
- Infrastructure commands: 60-300s timeouts

### Environment Variable Validation

Both Sentinel and Notifier validate required env vars at startup:
- Crash immediately with clear error if missing
- Never embed secrets as default values

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| GitHub API Rate Limiting | High | GitHub App tokens (5,000 req/hr), aggressive caching, long-polling |
| LLM Looping/Hallucination | High | Max steps timeout, cost guardrails, retry counter (>3 → stalled) |
| Concurrency Collisions | Medium | Assign-then-verify locking pattern |
| Container Drift | Medium | Stop worker between tasks, clean restart |
| Security Injection | Medium | HMAC validation, isolated network, credential scrubbing |

---

## References

- [OS-APOW Development Plan v4.2](./OS-APOW%20Development%20Plan%20v4.2.md)
- [OS-APOW Implementation Specification v1.2](./OS-APOW%20Implementation%20Specification%20v1.2.md)
- [OS-APOW Simplification Report v1](./OS-APOW%20Simplification%20Report%20v1.md)
- [OS-APOW Plan Review](./OS-APOW%20Plan%20Review.md)
- [Technology Stack](./tech-stack.md)
