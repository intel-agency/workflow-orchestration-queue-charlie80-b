# Workflow Orchestration Queue (OS-APOW)

> Headless agentic orchestration platform that transforms GitHub Issues into autonomous "Execution Orders"

[![CI](https://github.com/intel-agency/workflow-orchestration-queue-charlie80-b/actions/workflows/ci.yml/badge.svg)](https://github.com/intel-agency/workflow-orchestration-queue-charlie80-b/actions/workflows/ci.yml)

## Overview

OS-APOW (Open Source Agentic Project Orchestration Workflow) is a headless orchestration system that:

1. **Listens** for GitHub events via webhooks (The Ear)
2. **Polls** for issues labeled `agent:queued` (The Sentinel)
3. **Executes** AI-powered workflows in isolated devcontainers
4. **Reports** progress and results back to GitHub

## Architecture

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

## Project Structure

```
/
├── src/
│   ├── __init__.py              # Package initialization
│   ├── notifier_service.py      # FastAPI webhook receiver
│   ├── orchestrator_sentinel.py # Background polling service
│   ├── models/
│   │   ├── __init__.py
│   │   └── work_item.py         # Pydantic models
│   └── queue/
│       ├── __init__.py
│       └── github_queue.py      # GitHub API queue implementation
├── tests/
│   ├── __init__.py
│   └── test_work_item.py
├── plan_docs/                   # Planning documents
├── docs/                        # Documentation
├── pyproject.toml               # uv package management
├── Dockerfile                   # Container image
├── docker-compose.yml           # Multi-service orchestration
└── .ai-repository-summary.md    # Repository summary for AI agents
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.12+ |
| Web Framework | FastAPI |
| ASGI Server | Uvicorn |
| Data Validation | Pydantic |
| HTTP Client | httpx |
| Package Manager | uv |
| Containerization | Docker |
| CI/CD | GitHub Actions |

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Docker (optional, for containerized deployment)

### Local Development

1. **Clone the repository**
   ```bash
   git clone https://github.com/intel-agency/workflow-orchestration-queue-charlie80-b.git
   cd workflow-orchestration-queue-charlie80-b
   ```

2. **Install dependencies**
   ```bash
   uv sync --dev
   ```

3. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

4. **Run the notifier service**
   ```bash
   uv run uvicorn src.notifier_service:app --reload
   ```

5. **Run the sentinel (in another terminal)**
   ```bash
   uv run python -m src.orchestrator_sentinel
   ```

### Docker Deployment

```bash
# Build and run with Docker Compose
docker-compose up -d

# View logs
docker-compose logs -f
```

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GITHUB_TOKEN` | Yes | GitHub App Installation Token |
| `GITHUB_ORG` | Yes | Target organization |
| `GITHUB_REPO` | Yes | Target repository |
| `WEBHOOK_SECRET` | Yes* | HMAC secret for webhook verification |
| `SENTINEL_BOT_LOGIN` | No | Bot account for distributed locking |
| `SENTINEL_POLL_INTERVAL` | No | Polling interval in seconds (default: 60) |

*Required for notifier service only

## Testing

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=src --cov-report=term-missing

# Run linting
uv run ruff check src tests

# Run type checking
uv run mypy src
```

## API Endpoints

### Notifier Service

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/webhooks/github` | GitHub webhook receiver |
| `GET` | `/health` | Health check endpoint |

## Work Item Status Flow

```
agent:queued ──▶ agent:in-progress ──▶ agent:success
                     │
                     ├──▶ agent:error
                     │
                     └──▶ agent:infra-failure
```

## Documentation

- [Repository Summary](.ai-repository-summary.md) - AI-friendly repository overview
- [Architecture Guide](plan_docs/OS-APOW%20Architecture%20Guide%20v3.2.md)
- [Implementation Specification](plan_docs/OS-APOW%20Implementation%20Specification%20v1.2.md)
- [Tech Stack](plan_docs/tech-stack.md)

## Contributing

1. Create a feature branch
2. Make your changes
3. Run tests and linting
4. Submit a pull request

## License

MIT License - see [LICENSE](LICENSE) for details.
