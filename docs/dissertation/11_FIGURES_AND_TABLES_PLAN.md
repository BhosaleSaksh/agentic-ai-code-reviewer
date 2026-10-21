# Chapter 11: Figures and Tables Plan

**Project Title:** An Agentic AI Framework for Reliable and Evidence-Based Automated Code Review  
**Author:** Saksham Bhosale  
**Repository:** `D:\Projects\agentic-code-reviewer`  
**Execution Branch:** `feat/phase-7-evaluation`  

---

## 11.1 Figures Catalog and Specifications

This catalog provides reproducible, editable diagram specifications (in Mermaid.js and ASCII format) for every architectural, procedural, and empirical figure in the dissertation.

### Figure 1: Overall System Architecture
* **Placement:** Chapter 2 (Section 2.3) and Chapter 5 (Section 5.1).
* **Source Modules:** `backend/app/api/v1/webhooks.py`, `backend/app/services/diff_parser.py`, `backend/app/static_analysis/`, `backend/app/orchestration/review_graph.py`, `backend/app/services/github/review_publisher.py`.
* **Description:** Block diagram showing the end-to-end pipeline from incoming GitHub pull request webhook to final publication.

```mermaid
graph TD
    subgraph Ingestion ["1. Webhook & Workspace Ingestion"]
        A[GitHub PR Webhook] -->|HMAC Verification| B[FastAPI Webhook Handler]
        B -->|Async Enqueue| C[ARQ Worker / Redis Queue]
        C -->|Clone / Fetch| D[Workspace Manager]
        D -->|Unified Diff| E[DiffParserService]
    end

    subgraph StaticAnalysis ["2. Deterministic Static Tooling"]
        D -->|Changed Files| F[Bandit Security Runner]
        D -->|Changed Files| G[Semgrep Semantic Runner]
        D -->|Manifests| H[Pip-Audit CVE Runner]
        F --> I[Evidence Normalizer]
        G --> I
        H --> I
        I -->|List of EvidenceItems| J[(Normalized Evidence Context)]
    end

    subgraph LangGraphWorkflow ["3. Stateful Multi-Agent Graph (ReviewState)"]
        E --> K[Planner Agent]
        J --> K
        K -->|ReviewPlan.active_agents| L{Dynamic Fan-Out}
        L -->|Security Scope| M[Security Specialist]
        L -->|Logic Scope| N[Bug Logic Specialist]
        L -->|Error Scope| O[Error Handling Specialist]
        L -->|Test Scope| P[Test Adequacy Specialist]
        M --> Q[Candidate Findings Aggregator]
        N --> Q
        O --> Q
        P --> Q
        Q --> R[Evidence Grounding Engine]
        J --> R
        R -->|Grounded Candidates| S[Adversarial Critic Agent]
        S -->|Strict Verification Rubric| T[Verified Findings Filter]
    end

    subgraph Publication ["4. Safety Gating & Review Publishing"]
        T -->|Verified Findings| U{Safety Invariants}
        U -->|GITHUB_PUBLISH_REVIEWS == false| V[Log & Persist Only]
        U -->|GITHUB_PUBLISH_REVIEWS == true| W[GitHub Review Publisher]
        W -->|Multi-line Review Comment| X[GitHub PR Review Thread]
        T --> Y[(PostgreSQL Persistence)]
    end
```

---

### Figure 2: Review Sequence and Agent Interaction Workflow
* **Placement:** Chapter 5 (Section 5.4).
* **Source Modules:** `backend/app/orchestration/review_graph.py`, `backend/app/agents/`.
* **Description:** UML sequence diagram illustrating asynchronous message flow across graph nodes.

```mermaid
sequenceDiagram
    autonumber
    actor Dev as Developer / GitHub
    participant WH as Webhook Service
    participant WK as Review Worker
    participant DP as Diff Parser
    participant SA as Static Analysis Runners
    participant PL as Planner Agent
    participant SP as Specialist Agents
    participant EG as Grounding Engine
    participant CR as Adversarial Critic
    participant PB as Review Publisher

    Dev->>WH: Pull Request Opened / Synchronized
    WH->>WH: Verify HMAC SHA-256 Signature
    WH->>WK: Enqueue Review Job (review_run_id)
    WK->>DP: Parse Unified Diff & AST Lines
    DP-->>WK: ParsedDiff (Hunks, Valid Lines)
    par Concurrent Tool Execution
        WK->>SA: Run Bandit (AST Security)
        WK->>SA: Run Semgrep (Semantic Rules)
        WK->>SA: Run Pip-Audit (Dependency CVEs)
    end
    SA-->>WK: Normalized EvidenceItems
    WK->>PL: Invoke Planner(Diff, Evidence)
    PL-->>WK: ReviewPlan (Scope, Active Agents)
    par Fan-Out Specialist Execution
        WK->>SP: Security Agent (Bandit Grounded)
        WK->>SP: Bug Logic Agent (AST Invariants)
        WK->>SP: Error Handling Agent (Exceptions)
        WK->>SP: Test Adequacy Agent (Coverage)
    end
    SP-->>WK: Candidate Findings List
    WK->>EG: Match Findings to AST Diff Hunks & Tool Rules
    EG-->>WK: Grounded Candidate Findings
    loop For Each Candidate Finding
        WK->>CR: Challenge Finding(Evidence, Coordinate, Speculation)
        CR-->>WK: Decision (VERIFIED / REJECTED)
    end
    WK->>PB: Submit Verified Findings
    alt GITHUB_PUBLISH_REVIEWS is True
        PB->>Dev: Post Inline Review Thread
    else Safety Gated (Default)
        PB->>PB: Suppress GitHub Calls (Store Locally)
    end
```

---

### Figure 3: Adversarial Critic Verification Decision Tree
* **Placement:** Chapter 5 (Section 5.5) and Chapter 8 (Section 8.3).
* **Source Modules:** `backend/app/agents/critic.py`, `backend/app/prompts/critic.py`, `backend/app/schemas/verification.py`.
* **Description:** State decision tree utilized by the Critic Agent to evaluate candidate findings.

```mermaid
graph TD
    A[Specialist Candidate Finding] --> B{Is target line within<br/>added/modified diff hunk?}
    B -->|No| R1[REJECT: Unanchored Line Drift]
    B -->|Yes| C{Does finding cite<br/>verifiable code evidence?}
    C -->|No Evidence & Pure Speculation| R2[REJECT: Ungrounded Assumption]
    C -->|Static Tool Match OR Visible Logic Error| D{Does finding propose<br/>concrete syntax fix?}
    D -->|Vague Stylistic Nitpick| R3[REJECT: Low Actionability]
    D -->|Actionable Exploit / Bug Proof| E{Confidence Score >= 0.70?}
    E -->|No| R4[FLAG: Needs Human Confirmation]
    E -->|Yes| V[VERIFIED: Publish Finding]

    style V fill:#d4edda,stroke:#28a745,stroke-width:2px;
    style R1 fill:#f8d7da,stroke:#dc3545,stroke-width:2px;
    style R2 fill:#f8d7da,stroke:#dc3545,stroke-width:2px;
    style R3 fill:#f8d7da,stroke:#dc3545,stroke-width:2px;
    style R4 fill:#fff3cd,stroke:#ffc107,stroke-width:2px;
```

---

## 11.2 Tables Catalog and Data Sources

This catalog specifies all data tables in the dissertation, identifying their exact source run identifiers and files in `evaluation/results/`.

### Table 1: Benchmark Dataset Composition
* **Placement:** Chapter 4 (Section 4.1) and Chapter 7 (Section 7.1).
* **Source:** `evaluation/datasets/` directory manifests.
* **Content:** 23 cases (18 synthetic, 5 real-world open-source pull requests across 4 categories).

### Table 2: Comprehensive Five-Baseline Performance Comparison
* **Placement:** Chapter 1 (Executive Summary) and Chapter 7 (Section 7.2).
* **Sources:**
  - `evaluation/results/e130978a-1728-4f3e-903a-e58867070e9b/summary.json`
  - `evaluation/results/a1f820b7-c0ac-461e-a419-160919491cdc/summary.json`
  - `evaluation/results/d56531a3-3e3d-46cc-a0e1-240c6e4634c3/summary.json`
  - `evaluation/results/80467945-6c02-4f49-a2c9-f92cb8a23a9b/summary.json`
  - `evaluation/results/3b8d2539-07a3-40b5-9533-072b87debf93/summary.json`
* **Metrics:** Evaluated Cases (23), TP, FP, FN, Precision, Recall, F1-Score, False Discovery Rate (FDR), Relative FDR Reduction, Token Count, Operational Cost ($0.00).

### Table 3: Granular Category-Level Performance Breakdown
* **Placement:** Chapter 7 (Section 7.3).
* **Source:** `summary.json` under `category_breakdown` for each run identifier.
* **Content:** True Positives, False Positives, False Negatives, Precision, Recall, and F1 across BUG_LOGIC, ERROR_HANDLING, SECURITY, and TEST_ADEQUACY.

### Table 4: Real-World Pull Request Performance (Generalization Test)
* **Placement:** Chapter 7 (Section 7.5).
* **Source:** `cases.json` for cases starting with `REAL-` (`REAL-BUG-001`, `REAL-ERR-001`, `REAL-SEC-001`, `REAL-SEC-002`, `REAL-TEST-001`).
* **Content:** Granular case-by-case comparison between Static Only, Single-LLM Reviewer, and Full Agentic Framework.

### Table 5: Resource Telemetry and Latency Boundaries
* **Placement:** Chapter 7 (Section 7.6) and Chapter 8 (Section 8.4).
* **Source:** `summary.json` under `resource_usage` for each run.
* **Content:** API calls, Prompt Tokens, Completion Tokens, Total Tokens, Recorded Latency, and Latency Measurement Boundary (Neural Generation vs. Algorithmic Filter).
