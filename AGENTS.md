# AGENTS.md

> Project instructions for AI coding agents working on workflow-orchestration-queue.

---

## Project Overview

**Name:** workflow-orchestration-queue (OS-APOW)  
**Purpose:** Headless agentic orchestration platform that transforms GitHub Issues into autonomous "Execution Orders"  
**Primary Language:** Python 3.12+  
**Package Manager:** uv

OS-APOW (Open Source Agentic Project Orchestration Workflow) is a headless orchestration system that:

1. **Listens** for GitHub events via webhooks (The Ear / Notifier Service)
2. **Polls** for issues labeled `agent:queued` (The Sentinel)
3. **Executes** AI-powered workflows in isolated devcontainers
4. **Reports** progress and results back to GitHub

---

## Setup Commands

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Docker (optional, for containerized deployment)

### Installation

```bash
# Install dependencies (production)
uv sync

# Install dependencies (with dev tools)
uv sync --dev
```

### Environment Configuration

```bash
# Copy example environment file
cp .env.example .env
# Edit .env with your credentials
```

Required environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `GITHUB_TOKEN` | Yes | GitHub App Installation Token |
| `GITHUB_ORG` | Yes | Target organization |
| `GITHUB_REPO` | Yes | Target repository |
| `WEBHOOK_SECRET` | Yes* | HMAC secret for webhook verification |
| `SENTINEL_BOT_LOGIN` | No | Bot account for distributed locking |
| `SENTINEL_POLL_INTERVAL` | No | Polling interval in seconds (default: 60) |

*Required for notifier service only

### Running Services

```bash
# Run the notifier service (FastAPI webhook receiver)
uv run uvicorn src.notifier_service:app --reload

# Run the sentinel (background polling service) - in another terminal
uv run python -m src.orchestrator_sentinel
```

### Docker Deployment

```bash
# Build and run with Docker Compose
docker-compose up --build

# Run in background
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

---

## Project Structure

```
workflow-orchestration-queue/
├── src/
│   ├── __init__.py              # Package initialization
│   ├── notifier_service.py      # FastAPI webhook receiver ("The Ear")
│   ├── orchestrator_sentinel.py # Background polling service ("The Brain")
│   ├── models/
│   │   ├── __init__.py
│   │   └── work_item.py         # Pydantic models: WorkItem, TaskType, WorkItemStatus
│   └── queue/
│       ├── __init__.py
│       └── github_queue.py      # ITaskQueue ABC + GitHubQueue implementation
├── tests/
│   ├── __init__.py
│   └── test_work_item.py        # Unit tests for work item model
├── scripts/                     # Shell and PowerShell helper scripts
├── plan_docs/                   # Planning documents (external-generated)
├── docs/                        # Documentation
├── pyproject.toml               # uv package management, ruff/mypy config
├── uv.lock                      # Deterministic lockfile
├── Dockerfile                   # Multi-stage production image
├── docker-compose.yml           # Multi-service orchestration
└── .ai-repository-summary.md    # AI-friendly repository summary
```

### Key Components

| Component | Path | Description |
|-----------|------|-------------|
| Notifier Service | `src/notifier_service.py` | FastAPI webhook receiver for GitHub events |
| Sentinel Orchestrator | `src/orchestrator_sentinel.py` | Background polling service that processes queued work items |
| WorkItem Model | `src/models/work_item.py` | Unified work item model with status and task type enums |
| ITaskQueue | `src/queue/github_queue.py` | Abstract interface for queue backends |
| GitHubQueue | `src/queue/github_queue.py` | GitHub Issues-based queue implementation |

---

## Code Style

### Formatting & Linting

This project uses **Ruff** for both linting and formatting.

```bash
# Lint code
uv run ruff check src tests

# Format code
uv run ruff format src tests

# Format check (CI mode)
uv run ruff format --check src tests
```

### Style Conventions

- **Line Length:** 100 characters
- **Python Version:** 3.12+
- **Type Hints:** Required (mypy strict mode)
- **Imports:** Absolute imports from `src.`
- **Docstrings:** Use triple-quoted docstrings for modules, classes, and public functions

### Type Checking

```bash
# Run mypy type checker
uv run mypy src
```

### Ruff Rules

Configured in `pyproject.toml`:

- `E` - pycodestyle errors
- `W` - pycodestyle warnings
- `F` - pyflakes
- `I` - isort
- `B` - flake8-bugbear
- `C4` - flake8-comprehensions
- `UP` - pyupgrade
- `ARG` - flake8-unused-arguments
- `SIM` - flake8-simplify

---

## Testing Instructions

### Run Tests

```bash
# Run all tests
uv run pytest

# Run with verbose output
uv run pytest tests/ -v

# Run specific test file
uv run pytest tests/test_work_item.py -v

# Run specific test class
uv run pytest tests/test_work_item.py::TestScrubSecrets -v

# Run with coverage
uv run pytest --cov=src --cov-report=term-missing
```

### Test Organization

- Tests are located in the `tests/` directory
- Test files follow the pattern `test_*.py`
- Test classes group related tests (e.g., `TestWorkItem`, `TestScrubSecrets`)
- Uses pytest with `asyncio_mode = "auto"`

### CI Pipeline

The CI pipeline runs on push/PR to main and includes:

1. **lint** - Ruff linter and format check
2. **test** - pytest with coverage
3. **typecheck** - mypy type checking
4. **build** - Docker image build and push (main branch only)

---

## Architecture Notes

### System Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   GitHub        │────▶│  Notifier Service │────▶│  GitHub Issues  │
│   Webhooks      │     │  (FastAPI)        │     │  (Queue)        │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                           │
                                                           ▼
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   GitHub API    │◀────│  Sentinel        │◀────│  Poll Queue     │
│   (Status)      │     │  Orchestrator    │     │  (60s interval) │
└─────────────────┘     └────────┬─────────┘     └─────────────────┘
                                 │
                                 ▼
                        ┌──────────────────┐
                        │  DevContainer    │
                        │  Worker          │
                        │  (AI Agent)      │
                        └──────────────────┘
```

### Work Item Status Flow

```
agent:queued ──▶ agent:in-progress ──▶ agent:success
                     │
                     ├──▶ agent:error
                     │
                     └──▶ agent:infra-failure
```

### Key Patterns

1. **Strategy Pattern:** `ITaskQueue` interface allows swapping queue backends (GitHub, Linear, etc.)
2. **Dependency Injection:** FastAPI's `Depends()` for queue implementation
3. **HMAC Verification:** Webhook signature validation for security
4. **Credential Scrubbing:** All log output passes through `scrub_secrets()` before posting to GitHub

### Data Models

- **TaskType:** Enum for work types (PLAN, IMPLEMENT, BUGFIX)
- **WorkItemStatus:** Enum mapping to GitHub labels (agent:queued, agent:in-progress, etc.)
- **WorkItem:** Pydantic model containing all work item data

---

## PR and Commit Guidelines

### Branch Naming

- Feature branches: `feature/description`
- Bug fixes: `fix/description`
- Documentation: `docs/description`

### Commit Messages

- Use clear, descriptive commit messages
- Reference issue numbers when applicable
- Follow conventional commits format when possible:
  - `feat: add new feature`
  - `fix: resolve bug`
  - `docs: update documentation`
  - `refactor: code cleanup`
  - `test: add tests`

### PR Process

1. Create a feature branch from `main`
2. Make your changes
3. Run tests and linting locally:
   ```bash
   uv run ruff check src tests
   uv run ruff format src tests
   uv run pytest
   uv run mypy src
   ```
4. Push and create a pull request
5. Ensure CI passes
6. Request review

### GitHub Actions Pinning

All GitHub Actions must be pinned to full SHA (40 characters):

```yaml
# Correct
uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2

# Incorrect
uses: actions/checkout@v4
uses: actions/checkout@main
```

---

## Common Pitfalls

### Missing Environment Variables

Both the notifier service and sentinel require `GITHUB_TOKEN` to be set. The notifier also requires `WEBHOOK_SECRET`. Without these, the services will fail to start.

```bash
# Check environment
echo $GITHUB_TOKEN
echo $WEBHOOK_SECRET
```

### Type Annotation Issues

The project uses mypy strict mode. Missing type annotations will cause errors:

```python
# Wrong
def process_item(item):
    return item.status

# Correct
def process_item(item: WorkItem) -> WorkItemStatus:
    return item.status
```

### Async/Await in Tests

Tests involving async code need pytest-asyncio. The project is configured with `asyncio_mode = "auto"`:

```python
# Works automatically with auto mode
async def test_async_operation():
    result = await some_async_function()
    assert result is not None
```

### Credential Scrubbing

Always use `scrub_secrets()` before posting any log output to GitHub:

```python
from src.models.work_item import scrub_secrets

safe_log = scrub_secrets(raw_log_output)
```

### Import Paths

Use absolute imports from `src.`:

```python
# Correct
from src.models.work_item import WorkItem
from src.queue.github_queue import GitHubQueue

# Incorrect
from models.work_item import WorkItem
```

### Docker Compose Dependencies

The sentinel service depends on the notifier being healthy. If you restart services, the sentinel may need manual restart:

```bash
docker-compose restart sentinel
```

---

## API Endpoints

### Notifier Service

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/webhooks/github` | GitHub webhook receiver |
| `GET` | `/health` | Health check endpoint |
| `GET` | `/docs` | OpenAPI/Swagger documentation |

---

## Related Documentation

- [README.md](README.md) - Project documentation
- [.ai-repository-summary.md](.ai-repository-summary.md) - AI-friendly repository overview
- [plan_docs/tech-stack.md](plan_docs/tech-stack.md) - Technology stack details
- [plan_docs/architecture.md](plan_docs/architecture.md) - Architecture details
