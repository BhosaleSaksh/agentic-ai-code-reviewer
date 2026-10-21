# Chapter 6: Implementation

**Project Title:** An Agentic AI Framework for Reliable and Evidence-Based Automated Code Review  
**Author:** Saksham Bhosale  
**Repository:** `D:\Projects\agentic-code-reviewer`  
**Execution Branch:** `feat/phase-7-evaluation`  

---

## 6.1 Technology Stack and Module Architecture

The software architecture is implemented in modern Python 3.12, adhering to clean architecture principles, strict static typing (PEP 561, `py.typed`), and asynchronous non-blocking I/O.

### 6.1.1 Core Technologies
* **Language & Runtime:** Python 3.12.3 (via dedicated virtual environment `.venv`).
* **Web Framework:** FastAPI 0.110+ with Uvicorn ASGI server for high-throughput webhook ingestion and REST APIs.
* **Agent Orchestration:** LangGraph 0.0.30+ and LangChain Core 0.1.30+ for stateful, cyclic workflow graph execution.
* **Data Validation & Schemas:** Pydantic v2 (Pydantic Settings v2) enforcing strict runtime typing and structured JSON schema generation.
* **ORM & Database:** SQLAlchemy 2.0 (asyncio engine with `asyncpg` driver) targeting PostgreSQL 16.
* **Task Queue & Caching:** ARQ (Async Redis Queue) and Redis 7 for distributed, idempotent background review jobs.
* **Static Analysis Engines:** Bandit 1.7.8 (AST security), Semgrep 1.68+ (semantic pattern matching), Pip-Audit 2.7+ (dependency CVEs).
* **Local Inference Engine:** Ollama 0.40.4 executing `qwen3:4b-instruct` on dedicated local storage (`D:\AI\Ollama\models`).

### 6.1.2 Repository Directory Layout
The codebase is structured into cohesive domain modules:
```text
agentic-code-reviewer/
├── backend/
│   ├── app/
│   │   ├── api/v1/          # FastAPI routers (webhooks, health, dashboard)
│   │   ├── core/            # App settings, logging, telemetry configuration
│   │   ├── database/        # SQLAlchemy models and async session management
│   │   ├── github/          # Webhook HMAC verification and GitHub App client
│   │   ├── orchestration/   # LangGraph review workflow graph and ReviewState
│   │   ├── schemas/         # Canonical Pydantic schemas (findings, diffs, plans)
│   │   ├── services/        # Domain services (diff parser, LLM, grounding, publisher)
│   │   ├── static_analysis/ # Bandit, Semgrep, and Pip-Audit subprocess runners
│   │   └── workers/         # ARQ background task workers and job settings
│   └── tests/               # 58 test files covering unit, integration, and safety tests
├── evaluation/
│   ├── baselines/           # Baseline harness implementations (Single-LLM, Agentic, Ablations)
│   ├── datasets/            # Curated 23-case benchmark corpus (synthetic and real-world PRs)
│   ├── results/             # Committed, immutable benchmark runs and reproducibility artifacts
│   └── scripts/             # run_benchmark.py and analysis utilities
└── docs/                    # Architecture specifications, phase reports, and dissertation
```

---

## 6.2 Local LLM Provider Integration (Ollama)

To eliminate cloud API costs, guarantee data privacy for proprietary codebases, and avoid third-party rate limits, the framework features a native local LLM provider integration (`backend/app/services/llm/ollama_provider.py`).

### 6.2.1 Provider Abstraction & Architecture
The LLM subsystem implements an extensible provider interface rooted at `BaseLLMProvider` (`backend/app/services/llm/base.py`):
```python
class BaseLLMProvider(ABC):
    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse: ...

    @abstractmethod
    async def generate_structured(
        self, prompt: str, schema: type[T], system_prompt: str | None = None, **kwargs: Any
    ) -> tuple[T, LLMResponse]: ...
```

### 6.2.2 Native Ollama Client Implementation
`OllamaProvider` (`backend/app/services/llm/ollama_provider.py`) implements high-performance asynchronous communication with the local Ollama daemon via `httpx.AsyncClient`:
* **Endpoint:** Communicates with `POST /api/chat` using Ollama's native JSON protocol.
* **Structured JSON Enforcement:** Passes `format="json"` alongside an inlined Pydantic JSON Schema in the prompt, compelling the model (`qwen3:4b-instruct`) to constrain its autoregressive decoding directly to valid JSON.
* **Defensive JSON Cleaning:** If the model wraps JSON responses in markdown code fences (````json ... ````), `_clean_json_markdown()` automatically strips delimiters before parsing via `Pydantic.model_validate_json()`.
* **Zero-Cost Telemetry:** Accurately maps Ollama's `prompt_eval_count` and `eval_count` token metadata into `ResourceUsage`, computing an operational cost of **$0.00** USD for local inference.

### 6.2.3 Error Taxonomy and Timeout Handling
`OllamaProvider` and `LLMService` map raw HTTP exceptions into a structured error taxonomy:
* `LLMTimeoutError`: Raised when generation exceeds `OLLAMA_REQUEST_TIMEOUT_SECONDS` (configured to 120.0s for CPU/GPU inference).
* `LLMResponseMalformedError`: Raised when model output fails schema validation.
* `LLMProviderError`: Raised on network disconnection or daemon crashes.

In the LangGraph orchestration layer, timeouts occurring within a specialist agent are trapped by the `specialist_errors` reducer, allowing remaining specialists to proceed without crashing the review run.

---

## 6.3 Database Schema and Persistence Architecture

The persistence layer (`backend/app/database/models/`) is implemented using SQLAlchemy 2.0 with asynchronous declarative models:

```
+---------------------------------------------------------------------------------------------------+
|                                     DATABASE ENTITY-RELATIONSHIP                                  |
+---------------------------------------------------------------------------------------------------+
|                                                                                                   |
|    +-------------------+ 1       * +--------------------+ 1       * +-----------------------+     |
|    |    Repository     | --------> |    PullRequest     | --------> |       ReviewRun       |     |
|    +-------------------+           +--------------------+           +-----------------------+     |
|    | id: int (PK)      |           | id: int (PK)       |           | id: UUID (PK)         |     |
|    | full_name: str    |           | pr_number: int     |           | status: str           |     |
|    | github_repo_id    |           | head_sha: str      |           | review_plan: JSON     |     |
|    +-------------------+           | base_sha: str      |           | total_tokens: int     |     |
|                                    +--------------------+           | latency_seconds: Dec  |     |
|                                                                     +-----------------------+     |
|                                                                                 | 1               |
|                                            +------------------------------------+                 |
|                                            |                                                      |
|                                            | *                                  | *               |
|                                            v                                    v                 |
|                               +-------------------------+          +-------------------------+    |
|                               |         Finding         |          |      EvidenceItem       |    |
|                               +-------------------------+          +-------------------------+    |
|                               | id: UUID (PK)           |          | id: UUID (PK)           |    |
|                               | review_run_id: UUID(FK) |          | review_run_id: UUID(FK) |    |
|                               | category: IssueType     |          | source_tool: str        |    |
|                               | severity: SeverityLevel |          | rule_id: str            |    |
|                               | file_path: str          |          | file_path: str          |    |
|                               | line_start / line_end   |          | line_start / line_end   |    |
|                               | verification_status     |          | confidence: str         |    |
|                               +-------------------------+          +-------------------------+    |
|                                            | 1                                                    |
|                                            | *                                                    |
|                                            v                                                      |
|                               +-------------------------+                                         |
|                               |     ReviewFeedback      |                                         |
|                               +-------------------------+                                         |
|                               | id: UUID (PK)           |                                         |
|                               | finding_id: UUID (FK)   |                                         |
|                               | feedback_type: str      |                                         |
|                               | is_positive: bool       |                                         |
|                               +-------------------------+                                         |
+---------------------------------------------------------------------------------------------------+
```
*Figure 6.1: Relational entity-relationship model implemented in PostgreSQL.*

### 6.2.1 Schema Entities
* **`Repository` (`repository.py`):** Stores GitHub repositories, default branches, and installation IDs.
* **`PullRequest` (`pull_request.py`):** Tracks pull request numbers, head/base commit SHAs, and change metadata.
* **`ReviewRun` (`review_run.py`):** Stores the execution record of a review job, including serialized `review_plan`, execution durations, token counts, and completion status (`COMPLETED`, `FAILED`).
* **`Finding` (`finding.py`):** Represents candidate and verified review findings, tracking file coordinates, AST spans, issue types, and verification decisions.
* **`EvidenceItem` (`evidence_item.py`):** Stores normalized static analysis tool evidence linked to the review run.
* **`ReviewFeedback` (`review_feedback.py`):** Captures developer feedback (reactions `+1`/`-1`, comment edits, resolution events) to measure finding utility over time.

---

## 6.4 Asynchronous Worker Pipeline and Job Lifecycle

To ensure non-blocking operation during long-running static analysis and multi-agent LLM inference, the framework utilizes an asynchronous worker pipeline (`backend/app/workers/tasks.py`) powered by ARQ.

### 6.4.1 Job Execution Stages
When a pull request webhook is received, the worker executes the following multi-stage pipeline:
1. **Workspace Provisioning:** An isolated workspace directory is provisioned by `WorkspaceManager` (`backend/app/services/workspace_manager.py`). If configured, the Git repository is shallow-cloned at the PR head commit.
2. **Unified Diff Parsing:** The pull request diff is fetched from GitHub or the local Git workspace, and parsed into a structured `ParsedDiff`.
3. **Static Analysis Execution:** Bandit, Semgrep, and Pip-Audit runners execute concurrently over the changed files, emitting `EvidenceItem` records.
4. **LangGraph Review Workflow:** The review graph is compiled with a thread configuration (`review_run_id`), invoking the Planner, Specialists, Evidence Grounding Engine, and Adversarial Critic.
5. **Database Result Persistence:** Findings and execution telemetry are committed to PostgreSQL within an isolated database transaction.
6. **Gated GitHub Review Publication:** If `GITHUB_PUBLISH_REVIEWS=true`, the verified findings are published to the pull request via the GitHub API.

---

## 6.5 GitHub App Authentication and Publication Safety Gates

The GitHub integration subsystem (`backend/app/github/`) implements production-grade security and publication gating.

### 6.5.1 Cryptographic Authentication & Webhooks
* **HMAC SHA-256 Webhook Verification:** `GitHubWebhookVerifier` (`backend/app/github/verifier.py`) computes the HMAC digest of incoming raw request payloads using the secret configured in `GITHUB_WEBHOOK_SECRET`, employing constant-time string comparison (`hmac.compare_digest`) to prevent timing attacks.
* **GitHub App JWT & Token Minting:** `GitHubAppAuth` (`backend/app/github/auth.py`) signs JSON Web Tokens (RS256) using the GitHub App's private RSA key, exchanging JWTs for scoped installation access tokens valid for 60 minutes.

### 6.5.2 Multi-Tiered Publication Safety Invariants
To guarantee that automated reviews never post unverified comments to public pull requests, `GitHubReviewPublisher` (`backend/app/services/github/review_publisher.py`) enforces four mandatory safety invariants:
1. **Explicit Enablement Invariant:** Review publishing is strictly contingent on `settings.GITHUB_PUBLISH_REVIEWS == True`. In all testing and development environments, this flag defaults to `False`.
2. **Commit SHA Verification Invariant:** The publisher re-verifies that the target pull request's current live head commit SHA matches the exact commit analyzed by the review run. If an author pushes a new commit while the review is processing, the review is discarded to prevent stale comments.
3. **Evidence Filter Invariant:** Only findings marked as `VerificationStatus.VERIFIED` with `confidence_score >= 0.70` are converted into GitHub review comments.
4. **Coordinate Bounds Invariant:** The comment's target line is verified against the diff hunks; comments can only be anchored to valid changed lines.

---

## 6.6 Test Verification Suite and Code Coverage

The implementation is verified by an extensive automated test suite (`backend/tests/`).

### 6.6.1 Focused Verification Suite (100% Pass Rate)
A focused test suite of 74 unit and safety verification tests was executed using pytest (`python -m pytest`):
* `test_ollama_provider.py` (14 tests): Native client HTTP calls, JSON schema generation, streaming, timeout handling.
* `test_openai_provider.py` (11 tests): Fallback OpenAI provider tests.
* `test_real_llm_smoke.py` (4 tests): Live Ollama inference smoke tests validating `qwen3:4b-instruct`.
* `test_publication_safety_invariants.py` (5 tests): Strict verification that zero comments are posted when unconfigured.
* `test_evaluation_framework.py` (21 tests): Baseline harnesses, metric calculations, Wilson score intervals.
* `test_github_review_publisher.py` (12 tests): Markdown comment rendering, line coordinate mapping, publisher gating.
* `test_feedback_service.py` (7 tests): Developer reaction and comment correlation tracking.

**Result:** **74 PASSED, 0 FAILED** in 11.93 seconds (100% pass rate).

### 6.6.2 Full Repository Test Suite & Integration Boundaries
Executing the entire repository-wide test suite (570 test cases across 58 test files) yielded **495 PASSED, 48 FAILED, 22 SKIPPED, 5 ERRORS** in 1821.30s.

**Technical Diagnosis of Failures:**  
All 48 failures and 5 errors are strictly external infrastructure dependencies: they occur in integration tests (`test_database.py`, `test_redis.py`, `test_queue.py`, `test_webhooks.py`, `test_dashboard_api.py`) that require active Docker containers for PostgreSQL (port 5433), Redis (port 6380), and MinIO. When running in a lightweight developer environment where Docker Desktop is stopped, these integration tests fail fast on TCP connection refusal. Zero failures occur within core review logic, AST parsing, LLM providers, multi-agent orchestration, or publication safety gates.
