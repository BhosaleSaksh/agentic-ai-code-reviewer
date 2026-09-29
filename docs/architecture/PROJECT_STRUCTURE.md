# Repository Architecture & Directory Structure Guide

## 1. Top-Level Directory Layout
The repository is divided into decoupled, single-responsibility domains ensuring clear separation between backend API and agent runtimes, frontend dashboard interfaces, evaluation benchmarking suites, documentation, and operational scripts.

```
agentic-code-reviewer/
├── backend/          # Asynchronous backend, agent runtime, analysis tools, and task worker
├── frontend/         # React + TypeScript single-page dashboard application
├── evaluation/       # Benchmark datasets, ground-truth suites, baseline models, and metrics
├── tests/            # System-wide, end-to-end, and cross-cutting test suites
├── scripts/          # Operational, migration, and development automation scripts
├── docs/             # Authoritative specifications, architecture docs, ADRs, and API references
├── .env.example      # Safe environment variable configuration template
├── .gitignore        # Production gitignore rules
├── .gitattributes    # Cross-platform LF line-ending normalization rules
├── pyproject.toml    # Python dependency manifest, packaging definition, and tooling config
└── README.md         # Repository overview and entrypoint documentation
```

---

## 2. Backend Architectural Boundaries (`backend/`)
The backend is structured under `backend/app/` to establish strict modular boundaries. 

> [!IMPORTANT]
> **Cardinal Architecture Rule (Rule 2):**  
> **Zero business logic inside FastAPI route handlers.**  
> Route handlers (`backend/app/api/`) must only deserialize and validate incoming requests, check authentication/signatures, delegate execution to services or workers, and format HTTP responses. All computational, agentic, analysis, and persistence logic belongs strictly within their dedicated domain modules.

### Backend Subsystem Breakdown:
- **`backend/app/api/`:** HTTP and Webhook ingress layer.
  - Ingests GitHub webhooks (`POST /api/v1/webhooks/github`) with HMAC-SHA256 verification.
  - Exposes REST endpoints for review runs, finding triage, and Server-Sent Events (`GET /api/v1/reviews/{id}/trace`).
  - No database mutations or business calculations happen here directly.
- **`backend/app/agents/`:** Specialized AI agent implementations.
  - `SecurityAgent`: Detects OWASP Top 10, CWE violations, secrets, and insecure patterns.
  - `BugLogicAgent`: Identifies algorithmic flaws, off-by-one errors, and race conditions.
  - `ErrorHandlingAgent`: Identifies unhandled exceptions, resource leaks, and improper cleanup.
  - `TestAdequacyAgent`: Assesses coverage gaps, brittle assertions, and regression risks.
  - `CriticAgent`: Adversarial verification agent validating line existence, corroborating static evidence, and pruning hallucinations.
- **`backend/app/analysis/`:** Deterministic static analysis runners.
  - Isolates execution of Semgrep, Bandit, and pip-audit inside secure, network-disabled container sandboxes.
  - Normalizes tool outputs into canonical `EvidenceItem` records.
- **`backend/app/context/`:** Context gathering and AST extraction.
  - Unified diff parsing (`unidiff`), hunk boundary extraction, and enclosing scope extraction via Tree-sitter.
  - Semantic chunking for large pull requests (>400 LOC changed) without breaking method boundaries.
- **`backend/app/database/`:** Relational persistence layer.
  - SQLAlchemy async models (`Repository`, `PullRequest`, `ReviewRun`, `EvidenceItem`, `Finding`).
  - Alembic migrations, connection pool configuration, and database session management.
- **`backend/app/github/`:** GitHub API client & integration.
  - GitHub App authentication, JWT token generation, installation token refreshing.
  - Pull request diff retrieval, check run updates, and batch inline review comment publishing.
- **`backend/app/orchestration/`:** LangGraph workflow engine.
  - Defines the state machine graph (`ReviewState`), state checkpoints, node transitions, and map-reduce execution across specialists.
- **`backend/app/schemas/`:** Strict Pydantic v2 schemas.
  - Finding schemas, webhook event models, review plans, and API request/response contracts.
- **`backend/app/services/`:** Business logic domain services.
  - Scoping/triage service, review coordinator, deduplication engine, and confidence scoring.
- **`backend/app/workers/`:** Asynchronous task execution.
  - ARQ background worker functions processing review tasks dispatched from webhooks.
- **`backend/app/core/`:** Cross-cutting infrastructure.
  - Application configuration (`Settings` via `pydantic-settings`), security utilities, and structured logging.
- **`backend/app/evaluation/`:** Backend evaluation adapters connecting runtime traces to benchmark logging.
- **`backend/tests/`:** Backend unit and integration tests.

---

## 3. Frontend Architectural Boundaries (`frontend/`)
The frontend is a modern Single Page Application (SPA) designed with React 18+, TypeScript 5+, and Vite.

### Frontend Subsystem Breakdown (`frontend/src/`):
- **`components/`:** Reusable UI components (buttons, badges, modals, diff viewer panels, layout containers).
- **`features/`:** Feature-sliced modules (e.g., `reviews/`, `findings/`, `trace/`, `metrics/`).
- **`pages/`:** Top-level route views (Dashboard, Review Details, Live Execution Trace, Benchmark Analytics).
- **`services/`:** API client functions, Server-Sent Events (SSE) subscribers, and HTTP transport.
- **`hooks/`:** Custom React hooks (e.g., `useReviewTrace`, `useFindings`, `useSSE`).
- **`types/`:** TypeScript interfaces and type definitions mirroring backend Pydantic API schemas.
- **`lib/`:** Shared frontend utility functions, formatters, and color-coding logic.
- **`styles/`:** Global CSS design tokens, themes (dark/light), and typography styles.

---

## 4. Evaluation Boundaries (`evaluation/`)
The evaluation framework provides the empirical foundation for the capstone project, comparing the multi-agent framework against a single-LLM monolithic baseline.

### Evaluation Subsystem Breakdown:
- **`evaluation/datasets/`:** Curated pull request datasets (real-world and synthetic PRs across small, medium, and large LOC changes).
- **`evaluation/ground_truth/`:** Expert-labeled ground-truth findings specifying verified defect coordinates, CWE tags, and severity.
- **`evaluation/baselines/`:** Monolithic single-prompt LLM review baseline runners.
- **`evaluation/metrics/`:** Metric computation scripts calculating Precision, Recall, F1, False Positive Rate (FPR), False Negative Rate (FNR), Latency, and API Cost.
- **`evaluation/experiments/`:** Reproducible experiment execution harnesses and parameter sweeps (e.g., varying verification confidence thresholds from 0.50 to 0.90).
- **`evaluation/results/`:** Serialized benchmark outputs, confusion matrices, and markdown report tables.

---

## 5. Documentation Boundaries (`docs/`)
All technical specifications, architectural decisions, and API references reside in version-controlled documentation:
- **`docs/PROJECT_SPEC.md`:** Authoritative functional, non-functional, security, and KPI specifications.
- **`docs/ARCHITECTURE.md`:** Authoritative engineering rules, data flow diagrams, and system architecture.
- **`docs/ROADMAP.md`:** Phased implementation roadmap, dependencies, and milestone acceptance criteria.
- **`docs/ADR/`:** Architecture Decision Records documenting major design choices (e.g., `0001-postgresql-development-strategy.md`).
- **`docs/architecture/`:** Detailed component architecture guides, data contracts, and structural references.
- **`docs/api/`:** OpenAPI specs, webhook contract examples, and event sequence diagrams.
- **`docs/evaluation/`:** Benchmark methodology, statistical testing protocols, and dataset curation standards.
- **`docs/DEPENDENCIES.md`:** Dependency governance policy and lifecycle justifications.

---

## 6. Testing Boundaries
Testing is partitioned into distinct layers to maintain high test speed and reliability:
- **`backend/tests/unit/`:** Fast, isolated unit tests validating diff parsing, Pydantic schemas, chunking logic, and prompt generation without network or database dependencies.
- **`backend/tests/integration/`:** Integration tests running against real PostgreSQL, Redis, and mocked GitHub webhooks.
- **`tests/e2e/`:** End-to-end integration verifying complete webhook-to-database-to-review pipelines.
- **Coverage Mandate:** Core modules (diff parser, LangGraph nodes, Critic verification) must maintain $\ge 80\%$ test coverage in compliance with NFR-5.
