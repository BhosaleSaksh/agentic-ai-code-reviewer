# Dependency Management & Governance Policy

## 1. Overview & Philosophy
Every third-party dependency introduced into the **Agentic AI Code Reviewer** system expands the attack surface, increases deployment image size, and introduces maintenance overhead. In strict alignment with [ARCHITECTURE.md](ARCHITECTURE.md) Rule 16 (*"Do not introduce a new dependency without justification"*), dependencies are managed conservatively and categorized by lifecycle phase.

The primary manifest is [`pyproject.toml`](../pyproject.toml), utilizing standard PEP 621 metadata and optional dependency groups (`[project.optional-dependencies]`).

---

## 2. Dependency Taxonomy & Justification

### 2.1 Core Runtime Dependencies (Phase 1 Ingestion & Baseline)
Required for foundational application execution, asynchronous HTTP handling, and data contract validation:
- **`fastapi` ($\ge 0.110.0$):** High-performance asynchronous web framework providing automatic OpenAPI schema generation, dependency injection, and native `asyncio` compatibility for handling high-volume GitHub webhook traffic.
- **`uvicorn[standard]` ($\ge 0.28.0$):** Production-grade ASGI server utilizing `uvloop` and `httptools` for low-latency asynchronous request serving.
- **`pydantic` ($\ge 2.6.0$):** Core data validation engine enforcing strict Pydantic schemas (FR-14) for webhook payloads, internal representations, and candidate findings.
- **`pydantic-settings` ($\ge 2.2.0$):** Type-safe configuration management loading environment variables from `.env` with validation at startup.
- **`httpx` ($\ge 0.27.0$):** Asynchronous HTTP client for non-blocking communication with the GitHub REST API and external services.
- **`python-multipart` ($\ge 0.0.9$):** Streaming parser required by FastAPI for processing form-data and webhook payload envelopes.
- **`pyjwt[crypto]` ($\ge 2.8.0$):** Cryptographic JWT creation and token decoding library used for generating RS256-signed GitHub App authentication tokens.
- **`cryptography` ($\ge 42.0.0$):** Underlying cryptographic primitives enabling secure RSA private key parsing, PKCS#1/PKCS#8 PEM handling, and RS256 digital signature computation.


### 2.2 Database & Persistence Dependencies (`database` group - Phase 1)
Required for relational persistence and schema evolution:
- **`sqlalchemy[asyncio]` ($\ge 2.0.28$):** Asynchronous Object-Relational Mapper (ORM) and SQL expression engine powering repository, PR, and review persistence (FR-16).
- **`asyncpg` ($\ge 0.29.0$):** High-performance, native asynchronous PostgreSQL driver designed specifically for `asyncio`.
- **`alembic` ($\ge 1.13.1$):** Controlled, versioned database schema migration tool for continuous integration and production schema evolution.
- **`psycopg[binary]` ($\ge 3.1.18$):** Robust sync/async driver utility used as a fallback and for synchronous maintenance operations.

### 2.3 Task Queue & Caching Dependencies (`queue` group - Phase 1)
Required for background review execution and worker orchestration:
- **`arq` ($\ge 0.25.0$):** Lightweight, asynchronous job queuing engine built directly on Redis, enabling non-blocking execution of long-running review pipelines.
- **`redis[hiredis]` ($\ge 5.0.3$):** High-performance asynchronous Redis client with C-based parser for fast serialization and caching (FR-17).

### 2.4 Agentic AI & Orchestration Dependencies (`ai` group - Phases 3 & 4)
Required for stateful multi-agent DAG execution and model interaction:
- **`langgraph` ($\ge 0.0.30$):** Stateful multi-agent graph runtime enabling cyclical control flow, map-reduce fan-out across specialist agents, and checkpointing (FR-09).
- **`langchain-core` ($\ge 0.1.30$):** Fundamental abstractions for chat models, prompt templates, structured output parsing, and tool bindings.
- **`langchain-openai` / `langchain-anthropic` / `langchain-google-genai`:** Model provider adapters facilitating multi-vendor reasoning and zero-downtime model fallbacks (NFR-4, Section K).
- **`tenacity` ($\ge 8.2.3$):** Exponential backoff retry handler with jitter to gracefully handle LLM provider rate limits (HTTP 429) and transient network disconnects.

### 2.5 Code & Context Analysis Dependencies (`analysis` group - Phases 1 & 2)
Required for parsing diffs and extracting syntactic context:
- **`unidiff` ($\ge 0.7.5$):** Robust unified diff parser extracting added, modified, and deleted hunks along with exact line numbers and file boundaries (FR-02).
- **`tree-sitter` & `tree-sitter-python` ($\ge 0.21.0$):** Incremental AST parsing engine used for semantic decomposition of large pull requests without breaking class or method boundaries (FR-13).

### 2.6 Empirical Evaluation Dependencies (`evaluation` group - Phase 7)
Required for benchmarking the multi-agent system against single-LLM monolithic baselines:
- **`pandas` ($\ge 2.2.0$):** Tabular data processing for loading benchmark datasets, ground truth labels, and aggregating experiment runs.
- **`numpy` ($\ge 1.26.4$):** Statistical calculations, probability distribution analysis, and confidence calibration.
- **`scikit-learn` ($\ge 1.4.1$):** Standard evaluation metrics computation (Precision, Recall, F1-Score, False Positive Rate, Confusion Matrix).
- **`tabulate` ($\ge 0.9.0$):** Clean markdown and plain-text tabular formatting for academic reporting and terminal output.

### 2.7 Development & Quality Tooling (`dev` group)
Required for local development, linting, formatting, and test automation:
- **`pytest` & `pytest-asyncio` ($\ge 8.1.0$):** Test execution framework supporting asynchronous test fixtures and assertions.
- **`pytest-cov` ($\ge 5.0.0$):** Coverage analysis tool enforcing the $>80\%$ coverage standard across core modules (NFR-5).
- **`ruff` ($\ge 0.3.4$):** Ultra-fast Rust-based linter and code formatter. Replaces Flake8, Black, and isort in a unified configuration.
- **`mypy` ($\ge 1.9.0$):** Static type checker ensuring strict type safety and Pydantic v2 plugin integration.
- **`types-redis`:** Community type stubs enabling strict typing on Redis operations.
- **`pre-commit` ($\ge 3.7.0$):** Framework for managing Git hooks to ensure quality standards pass before commit.

---

## 3. Dependency Addition Policy
To prevent dependency bloat and security vulnerabilities, the following policy is enforced:
1. **Justification Requirement:** Every new package must solve a problem that cannot be addressed with the Python Standard Library in under 100 lines of maintainable code.
2. **Phase-Gated Introduction:** Dependencies must NOT be installed until the development phase requiring them begins.
3. **Packaging Standard:** Dependencies must be documented in `pyproject.toml` with version bounds and added to the appropriate optional group.
4. **License Compatibility:** Only permissive licenses (MIT, Apache 2.0, BSD, ISC) are permitted. Copyleft licenses (GPL, AGPL) are prohibited in core runtime modules.

---

## 4. Version Compatibility Policy
- **Python Support:** Minimum Python 3.11, tested against Python 3.12.
- **Pinned Minimum Versions:** All dependencies specify explicit lower bounds (`>=X.Y.Z`) corresponding to known stable releases supporting modern typing and Python 3.12.
- **No Upper-Bound Locking in Manifest:** Restrictive upper bounds (e.g., `<2.0.0`) are avoided in `pyproject.toml` unless an active breaking change is identified, preventing unnecessary dependency solver conflicts.

---

## 5. Security & Vulnerability Policy
1. **Automated Audit:** All dependencies will be periodically checked against the GitHub Advisory Database and PyPI vulnerability advisories via `pip-audit`.
2. **Zero Known High/Critical CVEs:** PRs introducing dependencies with unpatched High or Critical CVEs will be rejected.
3. **Container Isolation:** In accordance with NFR-4, static analysis tools (Semgrep, Bandit) execute in unprivileged, network-disabled Docker containers to isolate host and application runtimes.
