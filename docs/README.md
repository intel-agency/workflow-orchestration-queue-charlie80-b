# workflow-orchestration-queue Documentation

This directory contains the authoritative planning and architecture documents for the workflow-orchestration-queue project.

## Overview

workflow-orchestration-queue is a headless agentic orchestration platform that transforms standard project management artifacts (GitHub Issues) into autonomous execution orders fulfilled by specialized AI agents.

## Plan Documents

### Core Planning Documents

| Document | Description |
|----------|-------------|
| [OS-APOW Architecture Guide v3.2](./OS-APOW%20Architecture%20Guide%20v3.2.md) | System-level architecture, component overview, and security boundaries. Covers the Work Event Notifier, Work Queue, Sentinel Orchestrator, and Opencode Worker. |
| [OS-APOW Development Plan v4.2](./OS-APOW%20Development%20Plan%20v4.2.md) | Multi-phase development roadmap with guiding principles, user stories, and implementation milestones. |
| [OS-APOW Implementation Specification v1.2](./OS-APOW%20Implementation%20Specification%20v1.2.md) | Detailed technical specifications, requirements, test cases, and acceptance criteria for all system components. |

### Supplementary Documents

| Document | Description |
|----------|-------------|
| [OS-APOW Plan Review](./OS-APOW%20Plan%20Review.md) | Review and analysis of the planning documents. |
| [OS-APOW Simplification Report v1](./OS-APOW%20Simplification%20Report%20v1.md) | Simplification recommendations and architectural refinements. |

## System Architecture

The system is built on four conceptual pillars:

1. **The Ear (Work Event Notifier)** - FastAPI webhook receiver for event ingestion
2. **The State (Work Queue)** - Distributed state management via GitHub Issues
3. **The Brain (Sentinel Orchestrator)** - Persistent polling and task dispatch service
4. **The Hands (Opencode Worker)** - Isolated DevContainer for code execution

## Development Phases

- **Phase 0:** Seeding & Bootstrapping
- **Phase 1:** The Sentinel (MVP) - Autonomous polling & execution
- **Phase 2:** The Ear - Webhook automation
- **Phase 3:** Deep Orchestration & Self-Healing

## Related Documentation

- [Implementation Plan](./implementation-plan.md) - Implementation details and workflows
- [Orchestrator Supervisor](./orchestrator-supervisor.md) - Supervisor architecture
- [Routing Plan](./ROUTING_PLAN.md) - Event routing and handling
- [Workflow Issues and Fixes](./workflow-issues-and-fixes.md) - Known issues and resolutions

---

*These documents were migrated from `plan_docs/` as part of Phase 0 bootstrapping.*
