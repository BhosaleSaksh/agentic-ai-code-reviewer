# LangGraph Orchestration & Planner Agent Architecture

## 1. Overview & Architectural Role

Phase 3.1 introduces the initial probabilistic reasoning layer to the **Agentic AI Code Reviewer** system. Prior to this phase, the pipeline was strictly deterministic:
1. Webhook ingestion & verification (`PullRequestContext`)
2. Ephemeral workspace checkout (`WorkspaceContext`)
3. Multi-tool static analysis in Docker sandboxes (Semgrep, Bandit, pip-audit)
4. Canonical `EvidenceModel` normalization and PostgreSQL persistence (`EvidenceItem`)

Phase 3.1 bridges this deterministic foundation with an asynchronous, stateful orchestration graph managed by **LangGraph**. The workflow begins with a dedicated **Planner Agent** whose sole responsibility is to evaluate PR metadata, diff context, and static analysis evidence to construct a canonical `ReviewPlan`.

```
Deterministic Pipeline (Phase 1 & 2)
  ├── PullRequestContext (GitHub metadata, diff hunks)
  ├── WorkspaceContext (ephemeral checkout)
  └── Normalized EvidenceModel items (Semgrep, Bandit, pip-audit)
            │
            ▼
LangGraph Orchestration Graph (Phase 3.1)
  ├── [Node: prepare_review_context] (Bounds diffs, verifies commit SHA, deduplicates evidence)
  │         │
  │         ▼ (Conditional edge: check context validity)
  └── [Node: planner] (PlannerAgent invokes LLMService -> MockLLMProvider)
            │
            ▼
Canonical ReviewPlan
  ├── review_scope (FULL, SELECTIVE, MINIMAL, SKIP)
  ├── active_agents (e.g. security_agent, bug_logic_agent)
  ├── focus_areas (e.g. "JWT verification", "Input sanitization")
  ├── target_files (Prioritized file paths)
  └── reasoning (Explicit justification grounded in evidence)
            │
            ▼
Future Specialist Agents (Phase 3.2+)
```

> [!IMPORTANT]
> The Planner Agent **never** generates final `ReviewFinding` objects or writes pull request comments. It is purely an orchestrator and scoping agent.

---

## 2. LangGraph Review Graph Architecture

The workflow graph is implemented in [`backend/app/orchestration/review_graph.py`](file:///d:/Projects/agentic-code-reviewer/backend/app/orchestration/review_graph.py) utilizing `langgraph.graph.StateGraph`.

### 2.1 Graph Topology
- **`START` $\rightarrow$ `prepare_review_context`**: Verifies commit SHA alignment between the PR and static analysis evidence, sanitizes diff hunks, applies token/byte context limits, and structures the context for the agent.
- **`prepare_review_context` $\rightarrow$ `should_continue_to_planner` (Conditional Edge)**:
  - If context preparation succeeds $\rightarrow$ routes to `planner`.
  - If evidence validation or context bounding fails $\rightarrow$ routes directly to `END`, marking the state as `FAILED` with category `EVIDENCE_VALIDATION_FAILURE` or `CONTEXT_PREPARATION_FAILURE`.
- **`planner` $\rightarrow$ `END`**: Invokes the `PlannerAgent`, validates structured output against canonical `ReviewPlan`, enriches execution metadata/telemetry, and marks status as `COMPLETED`.

### 2.2 Extension for Future Specialist Agents
The graph is designed for non-invasive expansion in Phase 3.2+. In future phases, `planner` will branch via conditional fan-out edges into parallel specialist agents (`security_agent`, `bug_logic_agent`, etc.) using LangGraph map-reduce patterns without restructuring state or checkpointing.

---

## 3. Strongly Typed Graph State (`ReviewState`)

Graph state is defined in [`backend/app/orchestration/state.py`](file:///d:/Projects/agentic-code-reviewer/backend/app/orchestration/state.py) using a `TypedDict` schema (`total=False`):

| State Attribute | Type | Purpose |
| :--- | :--- | :--- |
| `review_run_id` | `str` | Unique execution identifier matching `ReviewRun.id` |
| `repository_id` | `int` | Internal database repository ID |
| `repository_full_name` | `str` | Full repository name (`owner/repo`) |
| `pr_number` | `int` | GitHub Pull Request number |
| `commit_sha` | `str` | 40-character hexadecimal head commit SHA |
| `base_sha` | `str \| None` | Target base branch commit SHA |
| `pr_title` | `str \| None` | Pull Request title (sanitized) |
| `pr_author` | `str \| None` | PR author login |
| `pr_metadata` | `dict[str, Any]` | Sanitized metadata (labels, branch names) |
| `workspace_metadata` | `dict[str, Any]` | Metadata only (paths, branch); **no raw workspace files** |
| `parsed_diff` | `dict[str, Any] \| None` | Serialized `ParsedDiff` dictionary |
| `changed_files` | `list[str]` | List of modified file paths |
| `diff_context_truncated` | `bool` | Flag indicating whether diff exceeded context limits |
| `evidence_items` | `list[dict[str, Any]]` | Serialized collection of normalized `EvidenceModel` items |
| `review_plan` | `dict[str, Any] \| ReviewPlan \| None` | Validated canonical review plan output |
| `status` | `str` | Lifecycle status (`PENDING`, `PREPARED`, `COMPLETED`, `FAILED`) |
| `error` | `str \| None` | High-level human-readable error description |
| `error_category` | `str \| None` | Programmatic category from `WorkflowErrorCategory` |
| `retry_count` | `int` | Number of retries attempted |
| `execution_metadata` | `dict[str, Any]` | Durations, token counts, model name, and triage chunks |

### 3.1 State Sanitization & Data Safety
- **No Secrets Allowed**: State initialization and update routines recursively inspect dictionary keys against `FORBIDDEN_KEY_PATTERNS` (`token`, `secret`, `password`, `private_key`, `api_key`, `authorization`).
- **No Raw Workspaces**: Host filesystem paths, raw source tree checkouts, or unparsed file contents are strictly barred from `ReviewState`.
- **Commit SHA Integrity**: `commit_sha` is verified using a strict 40-character hexadecimal regex (`COMMIT_SHA_PATTERN`).

---

## 4. Planner Agent Responsibility & Prompt Design

The **Planner Agent** is implemented in [`backend/app/agents/planner.py`](file:///d:/Projects/agentic-code-reviewer/backend/app/agents/planner.py) and prompted via [`backend/app/agents/planner_prompt.py`](file:///d:/Projects/agentic-code-reviewer/backend/app/agents/planner_prompt.py).

### 4.1 Core Responsibilities
1. **Analyze Diff Context**: Identify security-sensitive modules, critical business logic, error-handling mechanisms, and test additions/modifications.
2. **Evidence-First Scoping**: Actively incorporate deterministic findings from Semgrep, Bandit, and pip-audit:
   - If static analysis evidence is present, the Planner **must** activate `security_agent` and prioritize affected files.
   - If no static evidence is present, the Planner scopes review based on semantic risk (e.g. auth flows, concurrency, input handling).
3. **Prevent Premature Vulnerability Claims**: The Planner identifies areas requiring scrutiny; it does not declare vulnerabilities without downstream specialist verification.
4. **Emit Canonical `ReviewPlan`**: The output strictly validates against the existing Phase 1 schema (`app.schemas.review_plan.ReviewPlan`).

---

## 5. LLM Service Abstraction & Mock Provider

To isolate business logic from model provider APIs and satisfy the requirement for 100% offline, deterministic testing, an abstraction layer was created in [`backend/app/services/llm/`](file:///d:/Projects/agentic-code-reviewer/backend/app/services/llm/).

```
PlannerAgent / Future Agents
            │
            ▼
       LLMService
            ├── Bounded timeouts (asyncio.wait_for)
            ├── Structured Pydantic validation (generate_structured)
            ├── Error categorization (LLMTimeoutError, LLMProviderError, InvalidPlannerOutputError)
            │
            ▼
    BaseLLMProvider (Abstract Interface)
      ├── MockLLMProvider (Offline deterministic tests, zero credentials)
      └── [Future: LangChain/Direct Provider Adapters]
```

### 5.1 `MockLLMProvider` Capabilities
- Configurable default structured responses (`ReviewPlan`) or raw text.
- Deterministic error injection (`should_raise`) for timeouts, rate limits, or 500s.
- Multi-response replay (`response_sequence`) for testing retry loops.
- Latency simulation (`simulated_latency`) to verify timeout traps.
- Call counting and request introspection (`recorded_requests`).

---

## 6. Checkpointing Strategy

Graph state persistence is managed via [`backend/app/orchestration/checkpoint.py`](file:///d:/Projects/agentic-code-reviewer/backend/app/orchestration/checkpoint.py):

- **Thread Identity**: LangGraph checkpointer threads are configured strictly using `review_run_id`:
  ```python
  get_thread_config(review_run_id: str) -> RunnableConfig:
      return {"configurable": {"thread_id": str(review_run_id)}}
  ```
- **Checkpoint Isolation**: Checkpoints are partitioned strictly by `review_run_id`, preventing cross-review interference and supporting exact state inspection and resumption.
- **Storage Backend**: Defaulting to `MemorySaver` in Phase 3.1 ensures zero database migrations, zero external network dependency, and sub-millisecond execution overhead during testing. The factory (`create_checkpointer`) is structured to support Redis or Postgres savers in future phases.

---

## 7. Context Preparation, Bounding, & Large PR Triage

Context preparation is handled by [`PlannerContextBuilder`](file:///d:/Projects/agentic-code-reviewer/backend/app/orchestration/context_builder.py):

1. **Commit SHA Verification**: Guarantees that evidence from commit A is never planned against PR commit B (`EvidenceValidationError`).
2. **Diff Bounding**:
   - `max_diff_lines` (default 1,500) and `max_diff_bytes` (default 40,000 bytes).
   - If exceeded, hunks are truncated with explicit indicators, and `diff_context_truncated` is marked `True`.
3. **Sensitive File Filtering**: Files matching `FORBIDDEN_FILE_PATTERNS` (`.env`, `id_rsa`, `.pem`, `.key`, `id_ed25519`) have diff contents stripped before prompt inclusion.
4. **Evidence Prioritization & Deduplication**: Caps evidence items at `max_evidence_items` (default 50) and removes duplicate rule-file-line combinations.
5. **Large PR Partitioning**: If changed files exceed `large_pr_file_threshold` (default 15 files), the builder partitions files into architectural modules (`FILE_MODULE` triage strategy) for future chunked specialist execution.

---

## 8. Error and Retry Model

Defined in [`backend/app/orchestration/errors.py`](file:///d:/Projects/agentic-code-reviewer/backend/app/orchestration/errors.py):

```python
class WorkflowErrorCategory(StrEnum):
    INVALID_PLANNER_OUTPUT = "INVALID_PLANNER_OUTPUT"
    LLM_PROVIDER_ERROR = "LLM_PROVIDER_ERROR"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    CONTEXT_PREPARATION_FAILURE = "CONTEXT_PREPARATION_FAILURE"
    EVIDENCE_VALIDATION_FAILURE = "EVIDENCE_VALIDATION_FAILURE"
    WORKFLOW_CONFIGURATION_ERROR = "WORKFLOW_CONFIGURATION_ERROR"
    WORKFLOW_EXECUTION_FAILURE = "WORKFLOW_EXECUTION_FAILURE"
```

- **Transient Errors**: `LLMTimeoutError` and transient `LLMProviderError` (HTTP 429, HTTP 503) are marked `retryable=True`.
- **Deterministic Errors**: `InvalidPlannerOutputError`, `EvidenceValidationError`, and `WorkflowConfigurationError` are marked `retryable=False`. They immediately halt execution and fail the run rather than wasting LLM tokens on unrecoverable data corruption.

---

## 9. Observability & Security

- **Structured Logging**: Graph lifecycle events log `review_run_id`, `commit_sha`, stage durations, evidence item count, and token usage via standard Python `logging`.
- **Credential Hygiene**: No API keys, GitHub App private keys, webhook secrets, or database URLs are exposed in graph state, LLM prompts, exception traces, or log outputs.
- **Zero Real LLM Calls in Tests**: All automated test suites use `MockLLMProvider` and execute completely offline with zero vendor API keys.
