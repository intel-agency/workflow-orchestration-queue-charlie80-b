# OS-APOW Technology Stack

**Project:** workflow-orchestration-queue (OS-APOW)
**Generated:** 2026-03-22
**Status:** Planning

---

## Overview

OS-APOW is a headless agentic orchestration platform that transforms GitHub Issues into autonomous AI-driven development tasks. The technology stack is optimized for:

- **Async performance** - Non-blocking I/O for concurrent task management
- **Security** - HMAC webhook verification, credential scrubbing, network isolation
- **Reproducibility** - DevContainer-based execution environment
- **Self-bootstrapping** - System builds itself using its own orchestration capabilities

---

## Languages

| Language | Version | Purpose |
|----------|---------|---------|
| **Python** | 3.12+ | Primary language for orchestrator, API, and system logic |
| **PowerShell Core (pwsh)** | 7.x | Auth synchronization, cross-platform CLI interactions |
| **Bash** | - | Shell bridge scripts, Docker orchestration |

---

## Core Frameworks & Libraries

### Web Framework

| Component | Version | Purpose |
|-----------|---------|---------|
| **FastAPI** | Latest | Async web framework for webhook receiver (The Ear) |
| **Uvicorn** | Latest | ASGI server for FastAPI production deployment |
| **Pydantic** | Latest | Data validation, settings management, schema definitions |

### HTTP & Async

| Component | Version | Purpose |
|-----------|---------|---------|
| **HTTPX** | Latest | Async HTTP client for GitHub REST API calls |
| **asyncio** | Stdlib | Async/await patterns, background tasks, coroutines |

### Package Management

| Component | Version | Purpose |
|-----------|---------|---------|
| **uv** | 0.10.9+ | Rust-based Python package manager (replaces pip/poetry) |
| **pyproject.toml** | - | Project metadata and dependency specification |
| **uv.lock** | - | Deterministic lockfile for reproducible builds |

---

## AI/Agent Runtime

| Component | Version | Purpose |
|-----------|---------|---------|
| **opencode CLI** | 1.2.24 | AI agent runtime for worker execution |
| **ZhipuAI GLM** | - | Primary LLM provider (GLM-5 model) |

---

## Containerization & Infrastructure

| Component | Purpose |
|-----------|---------|
| **Docker** | Container runtime for worker isolation |
| **Docker Compose** | Multi-container orchestration |
| **DevContainers** | Reproducible development and execution environment |
| **GHCR** | Container registry for pre-built images |

---

## MCP Servers

| Server | Purpose |
|--------|---------|
| `@modelcontextprotocol/server-sequential-thinking` | Step-by-step analysis and planning |
| `@modelcontextprotocol/server-memory` | Knowledge graph for context persistence |

---

## GitHub Integration

| Component | Purpose |
|-----------|---------|
| **GitHub REST API** | Issue/PR management, label operations, comments |
| **GitHub Webhooks** | Event-driven task ingestion |
| **GitHub Projects V2** | Project tracking and visibility |
| **GitHub App** | Authentication and installation tokens |

---

## Development Tools

| Tool | Purpose |
|------|---------|
| **gh CLI** | GitHub operations from command line |
| **git** | Version control |
| **Node.js** | 24.14.0 LTS - Required for MCP server packages |
| **Bun** | 1.3.10 - Fast JavaScript runtime |

---

## State Management

| Approach | Description |
|----------|-------------|
| **Markdown as Database** | GitHub Issues used as distributed state |
| **Label-based State Machine** | `agent:queued` → `agent:in-progress` → `agent:success/error` |
| **Assignee Locking** | GitHub assignees used as distributed semaphore |

---

## Security Components

| Component | Implementation |
|-----------|----------------|
| **HMAC Verification** | X-Hub-Signature-256 for webhook validation |
| **Credential Scrubbing** | Regex-based sanitization for PATs, API keys |
| **Network Isolation** | Dedicated Docker network for workers |
| **Resource Constraints** | 2 CPUs / 4GB RAM per worker container |
| **Ephemeral Credentials** | In-memory env vars, destroyed on container exit |

---

## Required Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `GITHUB_TOKEN` | Yes | GitHub App installation token |
| `GITHUB_REPO` | Yes | Target repository (owner/repo format) |
| `SENTINEL_BOT_LOGIN` | Yes | Bot account login for distributed locking |

### Optional (with defaults)

| Variable | Default | Purpose |
|----------|---------|---------|
| `SENTINEL_POLL_INTERVAL` | 60 | Polling interval in seconds |
| `SENTINEL_MAX_BACKOFF` | 960 | Max backoff for rate limiting |
| `SENTINEL_HEARTBEAT_INTERVAL` | 300 | Heartbeat comment interval |
| `SENTINEL_SUBPROCESS_TIMEOUT` | 5700 | Max subprocess duration (95 min) |
| `WEBHOOK_SECRET` | - | HMAC secret for webhook validation |

---

## Directory Structure

```
workflow-orchestration-queue/
├── pyproject.toml              # uv dependencies and metadata
├── uv.lock                     # Deterministic lockfile
├── src/
│   ├── notifier_service.py     # FastAPI webhook ingestion
│   ├── orchestrator_sentinel.py # Background polling service
│   ├── models/
│   │   ├── work_item.py        # Unified WorkItem, TaskType, WorkItemStatus
│   │   └── github_events.py    # GitHub webhook payload schemas
│   └── queue/
│       └── github_queue.py     # ITaskQueue ABC + GitHubQueue
├── scripts/
│   ├── devcontainer-opencode.sh # Shell bridge to worker
│   ├── gh-auth.ps1             # GitHub auth utility
│   └── update-remote-indices.ps1 # Vector index sync
├── local_ai_instruction_modules/
│   ├── create-app-plan.md      # AI planning instructions
│   ├── perform-task.md         # Implementation instructions
│   └── analyze-bug.md          # Bug analysis instructions
├── tests/                      # Test suites
└── docs/                       # Documentation
```

---

## References

- [OS-APOW Architecture Guide v3.2](./OS-APOW%20Architecture%20Guide%20v3.2.md)
- [OS-APOW Development Plan v4.2](./OS-APOW%20Development%20Plan%20v4.2.md)
- [OS-APOW Implementation Specification v1.2](./OS-APOW%20Implementation%20Specification%20v1.2.md)
