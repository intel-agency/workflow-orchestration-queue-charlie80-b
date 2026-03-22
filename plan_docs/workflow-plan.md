# Workflow Execution Plan: `project-setup`

## 1. Overview

| Field | Value |
|-------|-------|
| **Workflow Name** | `project-setup` |
| **Workflow File** | `ai_instruction_modules/ai-workflow-assignments/dynamic-workflows/project-setup.md` |
| **Project Name** | `workflow-orchestration-queue` |
| **Repository** | `workflow-orchestration-queue-charlie80-b` |
| **Total Assignments** | 5 main assignments + 2 event assignments |

**Summary:** This workflow initializes a new headless agentic orchestration repository. It transforms a template clone into a fully configured development environment with project structure, documentation, and planning artifacts. The system is designed to be "self-bootstrapping" - once initialized, it can use its own orchestration capabilities to evolve.

---

## 2. Project Context Summary

### Key Facts

| Category | Details |
|----------|---------|
| **Purpose** | Headless agentic orchestration - transforms GitHub Issues into "Execution Orders" fulfilled by AI agents |
| **Tech Stack** | Python 3.12, FastAPI, uv (package manager), Pydantic, Docker/DevContainers, GitHub REST API |
| **Architecture** | 4 pillars: Ear (Notifier), State (Queue), Brain (Sentinel), Hands (Worker) |
| **Phases** | Phase 0: Seeding → Phase 1: Sentinel (MVP) → Phase 2: Ear (Webhooks) → Phase 3: Deep Orchestration |

### Repository Details

- **Template Repository:** `workflow-orchestration-queue-charlie80-b`
- **Existing Artifacts:** Reference implementations in `plan_docs/` (notifier_service.py, orchestrator_sentinel.py, src/models/, src/queue/)
- **Plan Documents:** Architecture Guide, Development Plan, Implementation Spec, Plan Review, Simplification Report

### Critical Directives

1. **GitHub Actions SHA Pinning:** All workflow actions MUST be pinned to full commit SHA (not version tags)
2. **Environment Variables:** Only 3 required (GITHUB_TOKEN, GITHUB_ORG, GITHUB_REPO) - others hardcoded per Simplification Report
3. **Environment Reset:** Hardcoded to "stop" mode (not "down" or "none")
4. **Polling:** Single-repo only (cross-repo Search API deferred to future phase)

---

## 3. Assignment Execution Plan

### Assignment 1: `init-existing-repository`

| Field | Content |
|-------|---------|
| **Goal** | Initialize repository with branch, GitHub Project, labels, and renamed files |
| **Key Acceptance Criteria** | ✅ Branch created (`dynamic-workflow-project-setup`) <br> ✅ GitHub Project created with columns <br> ✅ Labels imported from `.github/.labels.json` <br> ✅ Workspace/devcontainer files renamed <br> ✅ PR created to `main` |
| **Project-Specific Notes** | - Labels file is inside `.github/` directory, not root <br> - Workspace: `ai-new-app-template.code-workspace` → `workflow-orchestration-queue.code-workspace` <br> - Devcontainer name: `workflow-orchestration-queue-devcontainer` |
| **Prerequisites** | GitHub auth with `repo`, `project`, `read:project`, `read:user`, `user:email` scopes |
| **Dependencies** | None (first assignment) |
| **Risks / Challenges** | - GitHub permissions may be insufficient <br> - Branch creation must succeed before any other work |
| **Events** | Post-complete: `validate-assignment-completion`, `report-progress` |

---

### Assignment 2: `create-app-plan`

| Field | Content |
|-------|---------|
| **Goal** | Create comprehensive application plan from plan_docs, document as GitHub issue with milestones |
| **Key Acceptance Criteria** | ✅ Application template analyzed <br> ✅ Plan documented using issue template <br> ✅ Tech stack documented in `plan_docs/tech-stack.md` <br> ✅ Architecture documented in `plan_docs/architecture.md` <br> ✅ Milestones created for each phase <br> ✅ Issue linked to GitHub Project <br> ✅ `implementation:ready` label applied |
| **Project-Specific Notes** | - Plan docs are extensive - synthesize from all 5 documents <br> - 4 phases: Phase 0 (Seeding), Phase 1 (Sentinel), Phase 2 (Ear), Phase 3 (Deep Orchestration) <br> - Tech stack already defined: Python 3.12, FastAPI, uv, Pydantic, Docker <br> - **PLANNING ONLY** - no code implementation |
| **Prerequisites** | Repository initialized, plan_docs/ available |
| **Dependencies** | `init-existing-repository` (for branch, repo access) |
| **Risks / Challenges** | - Extensive documentation to synthesize <br> - Must not implement code - planning only |
| **Events** | Pre-begin: `gather-context` <br> Post-complete: `validate-assignment-completion`, `report-progress` <br> On-failure: `recover-from-error` |

---

### Assignment 3: `create-project-structure`

| Field | Content |
|-------|---------|
| **Goal** | Create solution structure, Docker/DevContainer configs, CI/CD workflows, and documentation |
| **Key Acceptance Criteria** | ✅ Solution/project structure created <br> ✅ Docker and docker-compose configured <br> ✅ CI/CD pipeline established <br> ✅ Documentation structure created <br> ✅ Repository summary document created (`.ai-repository-summary.md`) <br> ✅ All GitHub Actions pinned to SHA <br> ✅ Build validates successfully |
| **Project-Specific Notes** | - Python project with `pyproject.toml` (uv package manager) <br> - Source structure: `src/notifier_service.py`, `src/orchestrator_sentinel.py`, `src/models/`, `src/queue/` <br> - Reference implementations exist in `plan_docs/` - should be moved to main `src/` <br> - Must use `python -c "import urllib.request..."` for healthchecks (no curl in base image) <br> - 3 env vars only: GITHUB_TOKEN, GITHUB_ORG, GITHUB_REPO |
| **Prerequisites** | Application plan documented |
| **Dependencies** | `create-app-plan` (for architecture understanding) |
| **Risks / Challenges** | - SHA pinning for all GitHub Actions is critical <br> - Dockerfile must COPY src/ before editable install <br> - Healthcheck must use Python stdlib, not curl |
| **Events** | Post-complete: `validate-assignment-completion`, `report-progress` |

---

### Assignment 4: `create-agents-md-file`

| Field | Content |
|-------|---------|
| **Goal** | Create `AGENTS.md` at repository root with AI agent instructions |
| **Key Acceptance Criteria** | ✅ AGENTS.md exists at repository root <br> ✅ Contains project overview, tech stack <br> ✅ Contains validated build/test commands <br> ✅ Contains project structure layout <br> ✅ All commands validated by running them |
| **Project-Specific Notes** | - Document uv commands: `uv sync`, `uv run`, `uv run pytest` <br> - Document FastAPI dev: `uv run uvicorn src.notifier_service:app --reload` <br> - Reference existing scripts: `devcontainer-opencode.sh`, `gh-auth.ps1` <br> - Cross-reference with README.md and .ai-repository-summary.md |
| **Prerequisites** | Project structure created, README.md exists |
| **Dependencies** | `create-project-structure` (for commands to validate) |
| **Risks / Challenges** | - Must actually run all commands to validate them <br> - Environment may not have all dependencies yet |
| **Events** | Post-complete: `validate-assignment-completion`, `report-progress` |

---

### Assignment 5: `debrief-and-document`

| Field | Content |
|-------|---------|
| **Goal** | Create comprehensive debrief report capturing learnings, issues, and recommendations |
| **Key Acceptance Criteria** | ✅ Report created using structured template <br> ✅ All 12 sections complete <br> ✅ All deviations from assignments documented <br> ✅ Execution trace saved as `debrief-and-document/trace.md` <br> ✅ Report committed and pushed |
| **Project-Specific Notes** | - Must capture any Plan Review issues (I-1 to I-10) that weren't addressed <br> - Must document any Simplification Report items that weren't implemented <br> - Should provide recommendations for continuous improvement |
| **Prerequisites** | All prior assignments complete |
| **Dependencies** | All prior assignments |
| **Risks / Challenges** | - Must be thorough in capturing all deviations <br> - Execution trace must include all terminal output |
| **Events** | Post-complete: `validate-assignment-completion`, `report-progress` |

---

## 4. Sequencing Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                    PRE-SCRIPT-BEGIN EVENT                           │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  create-workflow-plan                                        │   │
│  │  → Creates: plan_docs/workflow-plan.md                       │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    MAIN ASSIGNMENTS                                 │
│                                                                     │
│  ┌──────────────────────────┐                                       │
│  │ 1. init-existing-repo    │                                       │
│  │    → Branch, Project,    │                                       │
│  │      Labels, PR          │                                       │
│  └────────────┬─────────────┘                                       │
│               │ validate + report                                   │
│               ▼                                                     │
│  ┌──────────────────────────┐                                       │
│  │ 2. create-app-plan       │                                       │
│  │    → Issue, Milestones,  │                                       │
│  │      tech-stack.md       │                                       │
│  └────────────┬─────────────┘                                       │
│               │ validate + report                                   │
│               ▼                                                     │
│  ┌──────────────────────────┐                                       │
│  │ 3. create-project-struct │                                       │
│  │    → src/, Docker, CI/CD │                                       │
│  └────────────┬─────────────┘                                       │
│               │ validate + report                                   │
│               ▼                                                     │
│  ┌──────────────────────────┐                                       │
│  │ 4. create-agents-md-file │                                       │
│  │    → AGENTS.md           │                                       │
│  └────────────┬─────────────┘                                       │
│               │ validate + report                                   │
│               ▼                                                     │
│  ┌──────────────────────────┐                                       │
│  │ 5. debrief-and-document  │                                       │
│  │    → Debrief Report,     │                                       │
│  │      trace.md            │                                       │
│  └────────────┬─────────────┘                                       │
│               │ validate + report                                   │
│               ▼                                                     │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    WORKFLOW COMPLETE
```

---

## 5. Open Questions

| # | Question | Impact | Recommendation |
|---|----------|--------|----------------|
| 1 | Should the reference implementations in `plan_docs/` (notifier_service.py, orchestrator_sentinel.py, src/) be moved to the main `src/` directory during `create-project-structure`? | Affects project structure creation | **Recommendation:** Yes, move them. The implementations are complete and validated per Plan Review. They should be the starting point for the project. |
| 2 | The Simplification Report marks several items as "IMPLEMENTED" (S-3, S-4, S-5, S-6, S-7, S-8, S-9, S-10, S-11). Should these be verified during project structure creation? | Affects code validation | **Recommendation:** Yes, verify that the implementations in `plan_docs/src/` reflect these simplifications. |
| 3 | Should the extensive plan_docs/ documentation be reorganized or consolidated? | Affects documentation structure | **Recommendation:** Keep as-is for now. The Plan Review notes that duplication aids autonomous agents. Consolidation can happen in a future iteration. |

---

## 6. Risk Register

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| GitHub permissions insufficient for Project creation | High | Medium | Run `scripts/test-github-permissions.ps1` before starting; use `-AutoFixAuth` |
| Branch creation fails | Critical | Low | This is the first step - all other work depends on it. Stop immediately if it fails. |
| GitHub Actions not pinned to SHA | High | Medium | Add explicit verification step in `create-project-structure` validation |
| Commands in AGENTS.md don't work | Medium | Medium | Must actually run all commands; document prerequisites clearly |
| Plan synthesis misses key requirements | Medium | Low | Reference all 5 plan documents; use Plan Review as checklist |

---

## Approval

**Status:** ✅ APPROVED

**Approved By:** Orchestrator Agent

**Date:** 2026-03-21

**Notes:** Plan approved for execution. The recommendations for open questions are accepted - move reference implementations to main src/, verify simplifications, and keep plan_docs/ as-is for now.
