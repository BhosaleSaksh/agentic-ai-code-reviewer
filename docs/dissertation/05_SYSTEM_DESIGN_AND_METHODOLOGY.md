# Chapter 5: System Design and Methodology

**Project Title:** An Agentic AI Framework for Reliable and Evidence-Based Automated Code Review  
**Author:** Saksham Bhosale  
**Repository:** `D:\Projects\agentic-code-reviewer`  
**Execution Branch:** `feat/phase-7-evaluation`  

---

## 5.1 Architectural Blueprint and Modular Decomposition

The architecture of the proposed Agentic AI Code Review Framework is structured around a pipeline of deterministic pre-processing, stateful multi-agent reasoning, deterministic evidence grounding, adversarial critic verification, and multi-tiered publication safety gates.

The system is decomposed into five primary subsystems, as depicted in **Figure 5.1**:
1. **Ingestion & Workspace Subsystem:** Ingests GitHub pull request webhooks, verifies HMAC signatures, clones/checks out target Git trees in isolated workspaces, and parses unified diffs.
2. **Deterministic Static Analysis Subsystem:** Orchestrates containerized runners for Bandit, Semgrep, and Pip-Audit, normalizing heterogeneous tool outputs into a unified `EvidenceItem` schema.
3. **Stateful Multi-Agent Orchestration Subsystem (LangGraph):** Manages an immutable, versioned `ReviewState` across a directed acyclic graph comprising a dynamic Planner Agent and parallel Specialist Agents.
4. **Evidence Grounding & Verification Subsystem:** Cross-references specialist candidate findings against normalized static evidence and AST diff boundaries, submitting candidate findings to an Adversarial Critic Agent for rigorous falsification.
5. **Publication & Telemetry Subsystem:** Formats verified findings into Markdown review comments, maps diff line numbers to GitHub review positions, enforces publication safety gates, and records complete cost/token telemetry.

```
+---------------------------------------------------------------------------------------------------------+
|                                    SYSTEM ARCHITECTURE OVERVIEW                                         |
+---------------------------------------------------------------------------------------------------------+
|                                                                                                         |
|   +-------------------+          +------------------------+          +------------------------------+   |
|   | GitHub Webhook    |  ----->  | Diff Parser & AST      |  ----->  | Static Analysis Subsystem    |   |
|   | /api/v1/webhooks  |          | Line Coordinate Mapper |          | (Bandit, Semgrep, Pip-Audit) |   |
|   +-------------------+          +------------------------+          +------------------------------+   |
|                                                                                      |                  |
|                                                                                      v Normalized Evid. |
|   +-------------------------------------------------------------------------------------------------+   |
|   |                  STATEFUL REVIEW WORKFLOW GRAPH (LangGraph / ReviewState)                       |   |
|   |                                                                                                 |   |
|   |        +-----------------------------------------------------------------------+                |   |
|   |        |                              PLANNER AGENT                            |                |   |
|   |        | (Evaluates Scope, Diffs, Complexity -> Constructs Bounded ReviewPlan) |                |   |
|   |        +-----------------------------------------------------------------------+                |   |
|   |                                            |                                                    |   |
|   |              +-----------------------------+-----------------------------+                      |   |
|   |              |                             |                             |                      |   |
|   |              v                             v                             v                      |   |
|   |    +-------------------+         +-------------------+         +-------------------+            |   |
|   |    |  SECURITY AGENT   |         |  BUG LOGIC AGENT  |         | ERROR HANDLING AG.|  ... etc.  |   |
|   |    | (Bandit/Semgrep Ev|         | (AST Logic Invar.)|         | (Exception Paths) |            |   |
|   |    +-------------------+         +-------------------+         +-------------------+            |   |
|   |              |                             |                             |                      |   |
|   |              +-----------------------------+-----------------------------+                      |   |
|   |                                            |                                                    |   |
|   |                                            v Candidate Findings                                 |   |
|   |        +-----------------------------------------------------------------------+                |   |
|   |        |                       EVIDENCE GROUNDING ENGINE                       |                |   |
|   |        |  (Matches Findings to Hunks, Rule IDs, Syntactical AST Line Boundaries)|                |   |
|   |        +-----------------------------------------------------------------------+                |   |
|   |                                            |                                                    |   |
|   |                                            v Grounded Candidate Findings                        |   |
|   |        +-----------------------------------------------------------------------+                |   |
|   |        |                       ADVERSARIAL CRITIC AGENT                        |                |   |
|   |        |  (Skeptical LLM Verification: Rejects Speculative & Unanchored Claims) |                |   |
|   |        +-----------------------------------------------------------------------+                |   |
|   |                                            |                                                    |   |
|   +-------------------------------------------------------------------------------------------------+   |
|                                                | Verified Findings                                      |
|                                                v                                                        |
|   +-------------------------------------------------------------------------------------------------+   |
|   |                              PUBLICATION & SAFETY SUBSYSTEM                                     |   |
|   |   * Safety Invariant: GITHUB_PUBLISH_REVIEWS == true ? Post Review : Log & Store                |   |
|   |   * Line Positioning: Map Diff Hunk Line -> GitHub Multi-line Review Comment Thread              |   |
|   |   * Database Persistence: PostgreSQL (ReviewRun, Finding, EvidenceItem, ReviewFeedback)        |   |
|   +-------------------------------------------------------------------------------------------------+   |
+---------------------------------------------------------------------------------------------------------+
```
*Figure 5.1: Architectural block diagram of the Agentic AI Code Review Framework.*

---

## 5.2 Diff Parsing and Lexical Coordinate Mapping

At the entry point of the pipeline, incoming pull request diffs are processed by `DiffParserService` (`backend/app/services/diff_parser.py`). Rather than passing raw unparsed text strings to the LLM, the system constructs a structured AST representation conforming to `ParsedDiff` (`backend/app/schemas/diff.py`).

### 5.2.1 Unified Diff Decomposition
For each modified file, the parser extracts:
* Target file paths (`old_path`, `new_path`).
* Change type (`ADDED`, `MODIFIED`, `DELETED`, `RENAMED`).
* Hunk headers and line intervals: `@@ -old_start,old_count +new_start,new_count @@`.
* Line-level classification:
  - `LineType.CONTEXT` (` `): Unchanged context line.
  - `LineType.ADDITION` (`+`): Added line with new line number.
  - `LineType.DELETION` (`-`): Removed line with old line number.

### 5.2.2 Exact Line Boundary Verification
To prevent LLM hallucination of invalid line numbers, the parser pre-computes an immutable lookup table of all valid, reviewable line numbers:
$$\mathcal{L}_{\text{valid}}(\text{file}) = \{L_{\text{new}} \mid \text{line has } \text{LineType.ADDITION} \text{ or } \text{LineType.CONTEXT}\}$$
Any candidate finding generated later whose line coordinate $L \notin \mathcal{L}_{\text{valid}}(\text{file})$ is rejected automatically by deterministic bounds checking prior to LLM evaluation.

---

## 5.3 Deterministic Static Analysis Subsystem

The static analysis pipeline (`backend/app/static_analysis/`) executes deterministic security and quality analyzers against the checked-out repository workspace.

### 5.3.1 Runner Implementations
Three specialized runner modules execute within containerized or isolated subprocess environments:
1. **`BanditRunner` (`backend/app/static_analysis/bandit_runner.py`):** Executes Bandit with `-f json` to discover security vulnerabilities in Python ASTs. Maps findings to CWE identifiers (e.g., `B608` $\to$ CWE-89 SQL Injection; `B501` $\to$ CWE-295 Unverified SSL).
2. **`SemgrepRunner` (`backend/app/static_analysis/semgrep_runner.py`):** Runs Semgrep utilizing curated security and logic rulesets (`p/ci`, `p/python`, `p/owasp-top-ten`).
3. **`PipAuditRunner` (`backend/app/static_analysis/pip_audit_runner.py`):** Evaluates dependency requirements against the PyPA advisory database, identifying supply chain vulnerabilities and known CVEs.

### 5.3.2 Evidence Normalization
Heterogeneous tool outputs are transformed into a canonical Pydantic model, `EvidenceItem` (`backend/app/schemas/evidence.py`):
```python
class EvidenceItem(BaseModel):
    id: UUID
    source_tool: ToolName  # BANDIT, SEMGREP, PIP_AUDIT
    rule_or_cve_id: str
    file_path: str
    line_start: int
    line_end: int
    severity: SeverityLevel
    confidence: ConfidenceLevel
    raw_output: dict[str, Any]
    matched_diff: bool
```
All evidence items whose coordinates intersect the pull request diff are flagged with `matched_diff = True`, forming the primary grounding context for agent reasoning.

---

## 5.4 Stateful Multi-Agent Workflow (LangGraph)

The core cognitive workflow is modeled as a stateful, cyclic directed graph using LangGraph (`backend/app/orchestration/review_graph.py`).

### 5.4.1 State Schema and Immutability
All graph nodes read from and write to a shared, immutable state structure, `ReviewState` (`backend/app/orchestration/state.py`):
```python
class ReviewState(TypedDict):
    review_run_id: str
    repository_full_name: str
    pr_number: int
    commit_sha: str
    changed_files: list[str]
    parsed_diff: dict[str, Any]
    evidence_items: Annotated[list[EvidenceItem], add]
    review_plan: ReviewPlan | None
    candidate_findings: Annotated[list[CandidateFinding], merge_candidate_findings]
    verified_findings: Annotated[list[VerifiedFinding], add]
    specialist_errors: Annotated[list[SpecialistError], add]
    status: Literal["PENDING", "IN_PROGRESS", "COMPLETED", "FAILED"]
```
Key reducers enforce deterministic data aggregation:
* `merge_candidate_findings`: Deduplicates candidate findings across specialists sharing the identical file path, line coordinate, and defect category.
* `specialist_errors`: Isolates agent timeouts or transient inference failures without crashing the entire review workflow.

### 5.4.2 State Transition Graph
The state transition model follows an explicit execution topology, illustrated in **Figure 5.2**:

```
                  [ START ]
                      |
                      v
             [ node_planner ]
                      |
                      | (Conditional Routing: ReviewPlan.active_agents)
         +------------+------------+------------+
         |            |            |            |
         v            v            v            v
    [ security ]  [ bug_logic ] [ error_h. ] [ test_adeq. ]
         |            |            |            |
         +------------+------------+------------+
                      |
                      v (Deduplication Reducer)
          [ node_aggregate_candidates ]
                      |
                      v
          [ node_evidence_grounding ]
                      |
                      v
             [ node_critic_agent ]
                      |
                      v
         [ node_final_aggregation ]
                      |
                      v
                   [ END ]
```
*Figure 5.2: LangGraph execution graph illustrating dynamic fan-out, evidence grounding, and critic verification.*

### 5.4.3 Agent Roles and Responsibilities
1. **Planner Agent (`PlannerAgent`):**  
   Analyzes pull request metadata, file list, unified diff complexity, and evidence summary. Outputs a structured `ReviewPlan` specifying the `review_scope` (`TRIVIAL`, `FOCUSED`, `FULL`), reasoning rationale, and dynamically selected `active_agents`.
2. **Specialist Agents (`SecurityAgent`, `BugLogicAgent`, `ErrorHandlingAgent`, `TestAdequacyAgent`):**  
   Specialists execute in parallel (fan-out). Each specialist operates under a specialized persona prompt with strict domain focus:
   * `SecurityAgent`: Specializes in CWE vulnerabilities, input validation, authentication, and cryptographic flaws, grounded by Bandit/Semgrep evidence.
   * `BugLogicAgent`: Specializes in algorithmic bugs, off-by-one errors, infinite loops, and inverted conditional branches.
   * `ErrorHandlingAgent`: Specializes in bare `except:` clauses, unhandled exceptions, swallowed tracebacks, and resource leaks.
   * `TestAdequacyAgent`: Evaluates whether newly introduced logic is covered by corresponding unit test assertions in test files.
3. **Adversarial Critic Agent (`CriticAgent`):**  
   Acts as an independent adversarial gatekeeper. Rather than cooperating with the specialists to find more bugs, the Critic is explicitly instructed to act as a **skeptical senior engineer**, challenging every candidate finding against an adversarial verification rubric.

---

## 5.5 Evidence Grounding and Critic Verification Protocol

The interaction between candidate findings, static evidence, and critic verification represents the core scientific novelty of this architecture.

### 5.5.1 The Verification Rubric
The Critic evaluates each candidate finding against four strict criteria:
1. **Diff Anchoring:** Is the flagged code located within an added or modified line of the pull request diff?
2. **Deterministic Evidence Support:** Is the finding substantiated by a static analysis finding (Bandit, Semgrep) or an unambiguous syntax/logic error visible in the hunk?
3. **Absence of Speculation:** Does the finding avoid assumptions about external unviewed code (e.g., claiming a variable is `None` when its initialization is outside the diff)?
4. **Actionability:** Does the finding provide a concrete, syntactically valid code fix rather than vague stylistic commentary?

### 5.5.2 Structured Verification Schema
The Critic outputs a structured decision conforming to `CriticVerificationResponse` (`backend/app/schemas/verification.py`):
```python
class CriticVerificationResponse(BaseModel):
    finding_id: str
    decision: VerificationStatus  # VERIFIED, REJECTED, NEEDS_HUMAN_CONFIRMATION
    verdict_explanation: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    grounds_for_rejection: list[str] = Field(default_factory=list)
    suggested_revision: str | None = None
```
Findings evaluated as `REJECTED` are permanently filtered out from the final publication list and preserved only in telemetry logs for auditability. Only findings with `decision == VERIFIED` and `confidence_score >= 0.70` advance to publication.

---

## 5.6 Publication Safety Controls

To ensure absolute safety in production deployments, the system implements multi-tiered publication safety gates (`backend/app/services/github/review_publisher.py`):

1. **Global Configuration Gate:**  
   Review comments are posted to GitHub if and only if `GITHUB_PUBLISH_REVIEWS=true` in application settings. By default, this flag is set to `false`, guaranteeing that no experimental or development runs leak comments to public pull requests.
2. **Live Head SHA Staleness Check:**  
   Before creating a review, the publisher queries the live GitHub API for the current pull request head commit SHA. If new commits were pushed during review processing ($\text{PR}.\text{head\_sha} \neq C_{\text{head}}$), the publication is aborted as stale.
3. **Zero-Comment Invariant on Empty Findings:**  
   If all candidate findings are rejected by the Critic (or if no defects are discovered), the system creates zero inline comments, preventing generic "Looks good to me!" spam.

---

## 5.7 Evaluation Methodology and Comparative Baseline Harness

To conduct a scientifically rigorous evaluation, the framework implements a standardized evaluation harness (`evaluation/baselines/` and `backend/tests/test_evaluation_framework.py`).

Five baseline configurations are evaluated over the identical benchmark corpus:
1. **`StaticAnalysisOnlyBaseline` (`evaluation/baselines/static_analysis.py`):** Pure deterministic tools (Bandit, Semgrep, Pip-Audit) with rule-based finding mapping and zero LLM calls.
2. **`SingleLLMBaseline` (`evaluation/baselines/single_llm.py`):** Standard monolithic code review using a single prompt requesting bug discovery over the unified diff, mimicking common zero-shot LLM review bots.
3. **`AgenticNoStaticEvidenceBaseline` (`evaluation/baselines/ablation.py`):** Multi-agent LangGraph workflow with Planner, Specialists, and Critic, but with static analysis tools disabled.
4. **`AgenticNoCriticBaseline` (`evaluation/baselines/ablation.py`):** Multi-agent workflow with static tools and Specialists, but with the Adversarial Critic bypassed (publishing all specialist candidate findings).
5. **`AgenticReviewerBaseline` (`evaluation/baselines/agentic.py`):** The full proposed framework unifying static tools, dynamic planning, specialist fan-out, evidence grounding, and adversarial critic verification.

Every baseline processes the exact same 23 benchmark cases in identical order, producing immutable execution artifacts (`cases.json`, `config.json`, `summary.json`, `metrics.csv`) to enable complete experimental reproducibility.
