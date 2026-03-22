# Workflow Orchestration Queue

GitHub Actions-based AI orchestration system for workflow automation.

## Overview

This project provides a robust workflow orchestration system that leverages GitHub Actions
to coordinate AI-powered automation tasks. It includes:

- **Notifier Service**: Handles notifications and event processing
- **Orchestrator Sentinel**: Coordinates workflow execution and monitoring
- **GitHub Queue**: Manages GitHub event queues and processing

## Requirements

- Python 3.12+
- uv package manager

## Installation

```bash
# Install dependencies
uv sync

# Install with dev dependencies
uv sync --extra dev
```

## Development

```bash
# Run tests
uv run pytest

# Run linter
uv run ruff check .

# Run type checker
uv run mypy src

# Format code
uv run ruff format .
```

## Project Structure

```
src/
  workflow_orchestration_queue/
    __init__.py
    notifier_service.py
    orchestrator_sentinel.py
    models/
      __init__.py
      work_item.py
      github_events.py
    queue/
      __init__.py
      github_queue.py
tests/
  __init__.py
```

## License

MIT License
