# Tech Stack: workflow-orchestration-queue

**Project:** workflow-orchestration-queue  
**Purpose:** Headless agentic orchestration platform that transforms GitHub Issues into autonomous "Execution Orders"  
**Last Updated:** 2026-03-21

---

## Languages

| Language | Version | Purpose |
|----------|---------|---------|
| Python | 3.12+ | Primary language for orchestrator, API webhook receiver, and all system logic. Chosen for async capabilities and robust text processing. |
| PowerShell Core (pwsh) | 7.x | Shell bridge scripts, GitHub auth synchronization, cross-platform CLI interactions |
| Bash | 5.x | Shell bridge scripts for Linux environments |

---

## Core Frameworks

| Framework | Version | Purpose |
|-----------|---------|---------|
| **FastAPI** | 0.110+ | High-performance async web framework for "The Ear" (webhook receiver). Native Pydantic integration, automatic OpenAPI generation. |
| **Uvicorn** | 0.27+ | Lightning-fast ASGI server for serving FastAPI application in production |
| **Pydantic** | 2.x | Strict data validation, settings management, and schema definitions for `WorkItem`, `TaskType`, `WorkItemStatus` |

---

## Key Packages

Managed via `pyproject.toml` and `uv.lock`:

| Package | Purpose |
|---------|---------|
| `fastapi` | Web framework for webhook endpoint |
| `uvicorn[standard]` | ASGI server with uvloop and httptools |
| `pydantic` | Data validation and settings management |
| `pydantic-settings` | Environment variable loading |
| `httpx` | Async HTTP client for GitHub REST API calls (replaces `requests`) |
| `python-dotenv` | `.env` file loading for local development |

---

## Package Management

| Tool | Version | Purpose |
|------|---------|---------|
| **uv** | 0.10+ | Rust-based Python package installer and resolver. Orders of magnitude faster than pip/poetry. Manages dependencies via `pyproject.toml` and `uv.lock`. |

### Dependency Files
- `pyproject.toml` — Core definition file for dependencies and project metadata
- `uv.lock` — Deterministic lockfile for exact package versions

---

## Infrastructure & Containerization

| Component | Purpose |
|-----------|---------|
| **Docker** | Worker container sandboxing, network isolation, resource constraints |
| **DevContainers** | High-fidelity development and execution environments for the Opencode Worker |
| **Docker Compose** | Multi-container orchestration (worker + dependencies like databases) |

### Container Specifications
- **Network Isolation:** Dedicated bridge network; workers cannot access host subnet
- **Resource Constraints:** 2 CPUs, 4GB RAM hard cap per worker
- **Ephemeral Credentials:** GitHub tokens injected as temporary env vars, destroyed on container exit

---

## External Services & APIs

| Service | Purpose |
|---------|---------|
| **GitHub REST API** | Primary queue backend (Issues, Labels, Comments, Assignees) |
| **GitHub App Webhooks** | Event-driven triggers for "The Ear" |
| **LLM Provider (GLM-5 / Claude)** | AI agent execution within the Worker container |

---

## Shell Bridge Scripts

The Orchestrator interacts with the Worker exclusively via shell scripts (ADR 07):

| Script | Purpose |
|--------|---------|
| `scripts/devcontainer-opencode.sh` | Core orchestrator: `up`, `start`, `stop`, `down`, `prompt` commands |
| `scripts/gh-auth.ps1` | GitHub App authentication synchronization |
| `scripts/common-auth.ps1` | Shared auth initialization logic |
| `scripts/update-remote-indices.ps1` | Vector index synchronization for codebase context |

---

## Observability & Logging

| Component | Purpose |
|-----------|---------|
| **Python logging** | Structured console output via `StreamHandler` (stdout captured by Docker) |
| **GitHub Issue Comments** | User-facing telemetry with credential scrubbing |
| **Heartbeat Comments** | Posted every 5 minutes for long-running tasks |
| **Local JSONL Logs** | Machine-readable audit trail (`worker_run_ID.jsonl`) |

---

## Security Components

| Component | Implementation |
|-----------|----------------|
| **Webhook Verification** | HMAC SHA256 signature validation against `WEBHOOK_SECRET` |
| **Credential Scrubbing** | Regex-based sanitization in `src/models/work_item.py` (`scrub_secrets()`) |
| **Token Patterns Scrubbed** | `ghp_*`, `ghs_*`, `gho_*`, `github_pat_*`, `Bearer`, `sk-*`, ZhipuAI keys |
| **Least Privilege** | GitHub App Installation Tokens scoped to minimum required permissions |

---

## Development Tools

| Tool | Purpose |
|------|---------|
| **opencode CLI** | AI agent runtime for Worker execution |
| **gh CLI** | GitHub API interactions and authentication |
| **git** | Version control and repository operations |

---

## Environment Variables

### Required (Phase 1 MVP)
| Variable | Purpose |
|----------|---------|
| `GITHUB_TOKEN` | GitHub App Installation Token for API access |
| `GITHUB_REPO` | Target repository (`owner/repo` format) |
| `SENTINEL_BOT_LOGIN` | GitHub login of the bot account for distributed locking |

### Optional (with defaults)
| Variable | Default | Purpose |
|----------|---------|---------|
| `SENTINEL_POLL_INTERVAL` | 60 | Polling interval in seconds |
| `WEBHOOK_SECRET` | — | HMAC secret for webhook verification (Phase 2) |

---

## Why This Stack?

1. **Python 3.12+** — Latest async features, improved error messages, performance gains
2. **FastAPI** — Native async, Pydantic integration, auto-generated API docs
3. **httpx** — True async HTTP client (unlike `requests`) for non-blocking GitHub API calls
4. **uv** — Blazing fast dependency resolution, essential for DevContainer build times
5. **DevContainers** — Bit-for-bit identical environments between AI worker and human developers
6. **Shell-First** — Reusing existing scripts ensures environment parity and reduces maintenance burden
