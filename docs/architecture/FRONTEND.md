# Phase 6: Frontend Architecture & Review Dashboard

## 1. Overview

The Phase 6 Frontend is a production-grade observability and review management interface for the **Agentic AI Code Reviewer** ("An Agentic AI Framework for Reliable and Evidence-Based Automated Code Review").

The interface provides complete visibility into:
1. Connected GitHub repositories and webhook activity.
2. Ingested Pull Requests and their commit review progression.
3. Multi-agent review execution runs and orchestration timelines.
4. Grounded candidate findings from specialized agents (Security, Bug/Logic, Error Handling, Performance, Maintainability, Test Adequacy).
5. Concrete evidence artifacts grounding detected issues (diff hunks, Semgrep rules, Bandit CVEs, AST context).
6. Critic verification status, rejection reasons, and suppression notes.
7. GitHub publication audits with verified-only publication guarantees.
8. Developer review feedback loop events (reactions, replies, resolutions).

---

## 2. Architecture & Design Principles

```
React 18 SPA (TypeScript + Vite)
    │
    ▼
Centralized Typed API Client (`lib/api/client.ts`)
    │
    ▼
FastAPI Read Endpoints (`/api/v1/...`)
    │
    ▼
Dashboard Service Layer (`DashboardService`)
    │
    ▼
PostgreSQL (ORM models) & Redis (review state / cache)
```

### Core Invariants:
1. **Source of Truth:** All business logic, verification verdicts, and publication eligibility decisions remain exclusively on the backend. The frontend is strictly an observability and management interface.
2. **Security & Privacy:**
   - The frontend never connects directly to PostgreSQL, Redis, GitHub API, or LLM providers.
   - No GitHub App private keys, installation tokens, database credentials, or LLM API keys exist anywhere in the frontend codebase or `VITE_*` environment variables.
   - Raw model prompts, system templates, and internal chain-of-thought are never exposed on client contracts or rendered in the DOM. Only persisted critic notes and structured rejection explanations are displayed.
3. **Publication Invariant Display:**
   - Findings in state `UNVERIFIED`, `REJECTED`, `SUPPRESSED_FALSE_POSITIVE`, or `DROPPED_LOW_CONFIDENCE` explicitly render a `NOT PUBLISHABLE` badge and can never be published from the UI.
   - Only `VERIFIED` findings display eligibility or published comments with GitHub inline thread links.

---

## 3. Technology Stack

- **Framework:** React 18 with TypeScript 5.6
- **Build Tool:** Vite 5
- **Routing:** React Router DOM 6
- **Server State Management:** TanStack React Query 5
- **Icons:** Lucide React
- **Design System:** Custom Dark Theme Vanilla CSS (design tokens, glassmorphism, responsive data tables, accessible contrast)
- **Testing:** Vitest 2, JSDOM, React Testing Library, Jest DOM

---

## 4. Directory Structure

```
frontend/
├── src/
│   ├── app/
│   │   ├── config/
│   │   │   └── env.ts               # Public environment configuration
│   │   ├── providers/
│   │   │   └── index.tsx            # QueryClientProvider & Global context
│   │   └── router/
│   │       └── index.tsx            # React Router route tree
│   │
│   ├── components/
│   │   ├── ui/
│   │   │   ├── Badge.tsx            # Base badge component
│   │   │   ├── SeverityBadge.tsx    # CRITICAL, HIGH, MEDIUM, LOW badges
│   │   │   ├── StatusBadge.tsx      # Lifecycle, verification, and publication badges
│   │   │   ├── Card.tsx             # Card container
│   │   │   ├── StatCard.tsx         # Dashboard metric card with icon & description
│   │   │   ├── LoadingState.tsx     # Animated loading spinner state
│   │   │   ├── ErrorState.tsx       # Accessible error card with retry button
│   │   │   └── EmptyState.tsx       # Contextual empty state with guidance
│   │   ├── layout/
│   │   │   ├── Layout.tsx           # Application shell layout
│   │   │   ├── Sidebar.tsx          # Primary navigation sidebar
│   │   │   └── Header.tsx           # Context header with backend status
│   │   ├── findings/
│   │   │   └── FindingCard.tsx      # Grounded finding card with critic notes
│   │   ├── evidence/
│   │   │   └── EvidenceCard.tsx     # Verifiable evidence snippet card
│   │   ├── reviews/
│   │   │   └── ReviewPipeline.tsx   # Visual multi-agent pipeline progress
│   │   └── feedback/
│   │       └── FeedbackCard.tsx     # Developer reaction and reply card
│   │
│   ├── features/
│   │   ├── dashboard/
│   │   │   └── DashboardPage.tsx    # Observability metrics & recent runs
│   │   ├── repositories/
│   │   │   ├── RepositoriesPage.tsx # Monitored repositories list
│   │   │   └── RepositoryDetailPage.tsx # Repository metadata & PRs
│   │   ├── pull-requests/
│   │   │   ├── PullRequestsPage.tsx # PR triage list with state filters
│   │   │   └── PullRequestDetailPage.tsx # PR lifecycle & review history
│   │   ├── review-runs/
│   │   │   ├── ReviewRunsPage.tsx   # Execution history with status filters
│   │   │   └── ReviewRunDetailPage.tsx # Execution pipeline, findings, evidence, publications, feedback
│   │   ├── findings/
│   │   │   └── FindingsPage.tsx     # Multi-filter findings explorer
│   │   └── feedback/
│   │       └── FeedbackPage.tsx     # Developer feedback audit log
│   │
│   ├── lib/
│   │   ├── api/
│   │   │   ├── client.ts            # Centralized typed HTTP client with error mapping
│   │   │   ├── dashboard.ts         # Dashboard metrics API
│   │   │   ├── repositories.ts      # Repositories API
│   │   │   ├── pullRequests.ts      # Pull requests API
│   │   │   ├── reviews.ts           # Review runs API
│   │   │   ├── findings.ts          # Findings API
│   │   │   └── feedback.ts          # Feedback API
│   │   ├── query/
│   │   │   └── queryKeys.ts         # Systematic TanStack Query key factory
│   │   └── utils/
│   │       ├── cn.ts                # Classname helper
│   │       └── formatters.ts        # SHA truncation, dates, durations, USD currency
│   │
│   ├── styles/
│   │   └── index.css                # Dark mode design tokens & CSS system
│   │
│   ├── test/
│   │   ├── setup.ts                 # Vitest test setup and DOM cleanup
│   │   ├── api-client.test.ts       # HTTP error mapping and security sanitization tests
│   │   └── app.test.tsx             # Application shell, security invariants, and UI tests
│   │
│   ├── types/
│   │   └── api.ts                   # Canonical TypeScript data contracts
│   │
│   ├── App.tsx                      # Root application component
│   └── main.tsx                     # Vite DOM entrypoint
│
├── index.html                       # HTML5 template with Inter & JetBrains Mono fonts
├── package.json                     # Scripts and dependencies
├── tsconfig.json                    # Strict TypeScript configuration
└── vite.config.ts                   # Bundler configuration & dev server proxy
```

---

## 5. Application Routes

| Path | Component | Purpose |
|---|---|---|
| `/` | `Navigate -> /dashboard` | Default root redirect |
| `/dashboard` | `DashboardPage` | Platform metrics (repositories, PRs, runs, findings, publications, feedback) and recent review executions |
| `/repositories` | `RepositoriesPage` | List of monitored GitHub repositories with PR counts |
| `/repositories/:repositoryId` | `RepositoryDetailPage` | Repository metadata, default branch, and PR history |
| `/pull-requests` | `PullRequestsPage` | Ingested PRs with status filter (ALL, OPEN, CLOSED, MERGED) |
| `/pull-requests/:pullRequestId` | `PullRequestDetailPage` | PR details, commit SHA, review lifecycle stage, and associated review runs |
| `/reviews` | `ReviewRunsPage` | Review execution audit history with status filter (ALL, COMPLETED, RUNNING, FAILED, PENDING) |
| `/reviews/:reviewRunId` | `ReviewRunDetailPage` | Deep inspection of a review run: visual pipeline, planner strategy, tabbed views for Findings, Evidence, Publications, and Feedback |
| `/findings` | `FindingsPage` | Global findings explorer with multi-dimensional filters (verification status, severity, issue type) |
| `/feedback` | `FeedbackPage` | Developer reaction and feedback audit log |

---

## 6. Centralized API Client & Server State

### API Client (`lib/api/client.ts`)
- Configured with `env.apiBaseUrl` (`/api/v1` default with Vite reverse proxy in development).
- Standardizes error responses into `ApiClientError` containing HTTP status code (`statusCode`), friendly message, and structured detail.
- Handles FastAPI error payload formats including single error strings and field validation arrays (`loc`, `msg`).
- **Sanitization:** Never propagates backend Python tracebacks, raw SQL errors, or internal file paths to UI components.

### TanStack Query Keys (`lib/query/queryKeys.ts`)
Query keys are structured hierarchically using a typed factory pattern:
- `queryKeys.dashboard.metrics`
- `queryKeys.repositories.list(limit, offset)`
- `queryKeys.repositories.detail(id)`
- `queryKeys.pullRequests.list(filters)`
- `queryKeys.pullRequests.detail(id)`
- `queryKeys.reviews.list(filters)`
- `queryKeys.reviews.detail(id)`
- `queryKeys.reviews.findings(id, filters)`
- `queryKeys.reviews.evidence(id)`
- `queryKeys.reviews.publications(id)`
- `queryKeys.reviews.feedback(id)`
- `queryKeys.findings.list(filters)`
- `queryKeys.feedback.list(filters)`

---

## 7. Local Development & Production Commands

### Backend:
```powershell
# Activate Python virtual environment and run backend server
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend:
```powershell
# Navigate to frontend directory
cd frontend

# Install dependencies (only required once)
npm install

# Start Vite dev server with proxy to backend (http://localhost:8000)
npm run dev

# Run TypeScript type check
npm run lint

# Run Vitest unit & integration test suite
npm run test

# Build production bundle
npm run build
```

---

## 8. Quality Assurance & Test Coverage

### Frontend Tests (`npm run test`):
16 unit and integration tests covering:
- Application shell navigation, branding, and backend connectivity indicator.
- Dashboard loading, error, and empty states.
- Verified finding publication eligibility invariant display (`ELIGIBLE TO PUBLISH`).
- Unverified finding publication security invariant (`NOT PUBLISHABLE`).
- Rejected finding display with critic rejection reasons.
- Verifiable evidence grounding card rendering.
- Developer feedback event card rendering.
- Visual review pipeline step flow.
- Non-leakage of sensitive secrets, tokens, or connection strings into DOM.
- API client HTTP error mapping (401, 403, 404, 409, 422, 500, 502).

### Backend Quality Gates:
- `504 passed, 0 failed` (all Phase 1–5 tests + 5 comprehensive dashboard API suites).
- Backend test coverage: 90%.
- Ruff check: 0 errors.
- Ruff format check: 173 files already formatted.
- Mypy check: 0 errors across 114 source files.
- Pip check: No broken requirements found.
