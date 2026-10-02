# GitHub Publishing & Feedback Loop Integration (Phase 5)

## 1. Overview & Architectural Objective

Phase 5 implements the verified GitHub publication layer and evaluation feedback foundation for the research project:
**"An Agentic AI Framework for Reliable and Evidence-Based Automated Code Review"**

While Phases 1–4 implemented PR ingestion, isolated workspace preparation, static analysis, LangGraph workflow orchestration, specialist agent ensembles, and Critic verification, Phase 5 connects verified findings directly to developer pull request discussions on GitHub.

### The Fundamental Invariant

```
UNVERIFIED FINDING
        ↓
      NEVER
        ↓
      GitHub
```

**Only findings with `verification_status == VerificationStatus.VERIFIED` may ever be published to GitHub.**

Candidate findings emitted by specialist agents, findings rejected by the Critic Agent, findings suppressed as false positives, or findings dropped due to low calibrated confidence are strictly blocked at the publication boundary.

---

## 2. Architectural Boundaries & Pipeline Flow

The publication subsystem strictly preserves existing layered boundaries:

```
FastAPI Router / Webhooks
        ↓
Services (WebhookService, ReviewJobQueueService)
        ↓
Orchestration (LangGraph ReviewGraph)
        ↓
Specialist Ensemble (Security, BugLogic, ErrorHandling, TestAdequacy)
        ↓
Evidence Grounding Engine & Critic Agent
        ↓ (VERIFIED Findings)
ReviewPublicationCoordinator
        ↓
GitHubReviewPublisher (Eligibility, Commit Safety, Idempotency, Positioning)
        ↓
GitHub REST API (Pull Request Review & Inline Comments)
        ↓
PostgreSQL Audit Persistence (ReviewPublication & ReviewFeedback)
```

### Boundary Constraints Enforced
- **No publishing in FastAPI route handlers**: Routes remain thin ingestion endpoints.
- **No publishing in LangGraph nodes**: Graph nodes solely compute analysis state.
- **No publishing in Specialist Agents**: Specialists only emit candidate findings.
- **No publishing in CriticAgent**: The Critic verifies evidence; it does not communicate with GitHub.
- **No publishing in Database Models**: Models are pure declarative schema entities.
- **Single Authentication Architecture**: Reuses `GitHubAppAuthenticator` and `GitHubClient` without duplicating token generation.

---

## 3. Subsystem Architecture

### 3.1 GitHub Review Publisher (`app.services.github.review_publisher`)
The `GitHubReviewPublisher` coordinates atomic publication of pull request reviews. It:
1. Validates commit SHA consistency against the live PR head commit.
2. Independently filters findings for `VERIFIED` status.
3. Checks idempotency keys to prevent duplicate comments.
4. Validates diff hunk positioning, partitioning findings into inline comments and summary fallbacks.
5. Formats comments and top-level summary markdown.
6. Submits atomic reviews via the GitHub REST API (`POST /repos/{owner}/{repo}/pulls/{number}/reviews`).
7. Persists publication audit records in PostgreSQL.

### 3.2 Comment Mapping (`app.services.github.comment_mapper`)
Converts `ReviewFinding` into clean GitHub Markdown comments:
- **Severity Badge**: Distinct visual indicator (`🚨 CRITICAL`, `⚠️ HIGH`, `⚡ MEDIUM`, `ℹ️ LOW`, `💡 INFO`).
- **Issue Section**: Root cause analysis and explanation.
- **Evidence Section**: Verifiable citations with file paths, line ranges, corroborating tool names, and rule IDs.
- **Recommendation Section**: Actionable fix instructions.
- **Suggested Fix Block**: Formatted GitHub suggestion block (````suggestion ... ````) enabling one-click developer application.
- **Zero Information Leakage**: Strips all internal chain-of-thought, critic notes, agent names, raw confidences, and model prompts.

### 3.3 Commit SHA Safety
Before any comment or review is published, the publisher validates:
```python
finding.commit_sha == current_pr_head_sha
```
If the finding was computed against a commit SHA that differs from the live PR head SHA, publication is aborted immediately with `PublishStaleCommitError`. This prevents outdated review comments from being attached to modified code.

### 3.4 Finding Eligibility Enforcement (`app.services.github.eligibility`)
The `FindingEligibilityValidator` enforces the verification invariant independently of callers:
```python
if finding.verification_status != VerificationStatus.VERIFIED:
    raise PublishValidationError(...)
```
Ineligible findings are recorded with status `SKIPPED` in the database audit log.

### 3.5 Diff Positioning & Anchoring
GitHub's Review API rejects comments on lines outside the pull request's diff hunks. The `PositioningValidator` validates line coordinates against `ParsedDiff`:
- **Line inside diff hunk**: Comment is attached inline at the exact line coordinate.
- **Line outside diff hunk**: Comment is **not** discarded and no false position is fabricated. Instead, the finding falls back into a dedicated section in the top-level review summary:
  `### 📌 Additional Findings (Outside Changed Lines)`.

### 3.6 Idempotency & Duplicate Prevention (`app.services.github.publication_service`)
To ensure that retries or repeated webhook triggers never produce duplicate GitHub comments, deterministic idempotency keys are enforced:
- **Individual Finding Key**: `{repository_id}:{pr_number}:{finding_id}:{commit_sha}`
- **Top-Level Review Key**: `{repository_id}:{pr_number}:review:{review_run_id}:{commit_sha}`

Before sending API requests, the publisher checks the `review_publications` table. If a matching publication is already marked as `PUBLISHED`, the operation returns an idempotent success result without calling the GitHub API.

### 3.7 Database Persistence & Migration
A dedicated, fully reversible Alembic migration (`0003_github_publishing_and_feedback.py`) adds:
- `review_publications`: Stores publication ID, review run ID, finding ID, repo/PR identity, commit SHA, idempotency key (unique index), GitHub review ID, GitHub comment ID, publication status (`PENDING`, `PUBLISHED`, `FAILED`, `SKIPPED`), timestamps, and failure diagnostics.
- `review_feedback`: Stores reviewer actions, dismissals, resolutions, replies, and reactions for scientific evaluation.

### 3.8 API Error Taxonomy & Retry Strategy (`app.services.github.errors`)
Errors are strictly categorized:
| Error Type | Category | Action |
| :--- | :--- | :--- |
| `PublishAuthenticationError` (401) | Non-Retryable | Fail immediately |
| `PublishPermissionError` (403) | Non-Retryable | Fail immediately |
| `PublishValidationError` (422 / schema) | Non-Retryable | Fail immediately / fallback |
| `PublishStaleCommitError` | Non-Retryable | Abort immediately |
| `DuplicatePublicationError` | Non-Retryable | Return idempotent result |
| `PublishRateLimitError` (429) | Retryable | Bounded exponential backoff + jitter |
| `PublishNetworkError` (timeout / transport) | Retryable | Bounded exponential backoff + jitter |
| `PublishServerError` (5xx) | Retryable | Bounded exponential backoff + jitter |

Retry formula:
$$\text{delay} = \min(\text{max\_delay}, \text{base\_delay} \times 2^{\text{attempt}-1}) + \text{jitter}$$

### 3.9 Feedback Loop Foundation (`app.services.github.feedback_service`)
Captures developer reactions and review feedback without altering active model weights:
- **Reactions**: Thumbs up (`+1`), thumbs down (`-1`), heart, etc. mapped to `FeedbackType.REACTION_POSITIVE` or `FeedbackType.REACTION_NEGATIVE`.
- **Reviewer Replies**: Thread replies linked to findings via comment IDs.
- **Review Decisions**: Approved reviews (`FINDING_ACCEPTED`) and change requests (`FINDING_REJECTED`).
- **Dismissals**: Review comments deleted or dismissed.

---

## 4. Security Boundaries

1. **Zero Credential Storage**: Private keys and installation access tokens are never persisted in the database.
2. **Safe Logging**: All Authorization headers and tokens are excluded from application logs.
3. **Comment Sanitization**: Only user-facing finding explanations and recommendations are posted to GitHub; no internal prompts, tokens, or system metadata are exposed.
4. **Isolated Database Relations**: Cascade deletes on review runs cleanly purge audit records without affecting primary repository configs.
