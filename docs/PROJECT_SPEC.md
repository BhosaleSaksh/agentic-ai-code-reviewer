# Project Specification

**Title:** An Agentic AI Framework for Reliable and Evidence-Based Automated Code Review  
**Author / Candidate:** Bhosale Sakshi  
**Academic Degree:** Final-Year Engineering Capstone Project  
**Repository:** [agentic-ai-code-reviewer](https://github.com/BhosaleSaksh/agentic-ai-code-reviewer.git)  

---

## 1. Executive Summary & Abstract

Code review is a cornerstone of modern software quality assurance and security compliance. While Large Language Models (LLMs) demonstrate exceptional code comprehension, standard single-prompt LLM code reviewers suffer from severe engineering limitations:
1. **Hallucination of non-existent bugs** and non-existent line numbers.
2. **High False Positive Rates (FPR)**, causing developer alert fatigue.
3. **Lack of empirical grounding**, offering subjective style opinions rather than concrete evidence.
4. **Context window saturation** and attention degradation on large Pull Requests.
5. **Absence of verification**, publishing speculative critiques directly to developers.

This project designs and implements an **Agentic AI Framework for Reliable and Evidence-Based Automated Code Review**. By orchestrating specialized analysis agents (Security, Bug/Logic, Error Handling, Test Adequacy) within a stateful **LangGraph** Directed Acyclic Graph (DAG), coupling them with deterministic static analysis tools (**Semgrep**, **Bandit**, **pip-audit**), and validating all claims using an adversarial **Critic/Verification Agent**, the framework ensures that every published PR comment is evidence-backed, line-accurate, and actionable.

---

## 2. Problem Statement & Motivation

Modern continuous integration workflows require fast, automated feedback on Pull Requests without overwhelming human reviewers. Existing automated tools fall into two unsatisfactory extremes:
- **Static Analysis Tools (AST linters):** Highly reliable and deterministic, but rigid, noisy, and blind to semantic business logic bugs, complex concurrency errors, or architectural regressions.
- **Single-LLM Reviewers:** Broad contextual understanding, but non-deterministic, prone to hallucinations, unable to verify their own outputs, and lacking grounded evidence chains.

**Core Research Question:**  
*Can a multi-agent orchestrated architecture, combining static analysis evidence collection with adversarial critic verification, achieve significantly higher precision and lower false positive rates in automated Pull Request code review than single-LLM monolithic baselines?*

---

## 3. Project Scope

### 3.1 In-Scope
- **VCS Integration:** Full GitHub Pull Request integration using GitHub Webhooks (HMAC-SHA256 verified) and the GitHub REST API (installation tokens via GitHub App).
- **Context Extraction:** Retrieval and parsing of unified diffs, modified files, commit metadata, and enclosing AST context.
- **Planning & Dynamic Triage:** Automated triage of PR changes to decide relevant review areas and activate appropriate agents.
- **Specialized AI Agents:**
  - Security Analysis Agent (OWASP Top 10, CWE patterns, secrets, sanitization).
  - Bug & Logic Analysis Agent (algorithmic bugs, edge cases, invariants, concurrency).
  - Error Handling Analysis Agent (exceptions, resource leaks, silent failures).
  - Test Analysis Agent (branch coverage gaps, regression risks, assertion quality).
- **Deterministic Static Analysis:** Dockerized, isolated execution of Semgrep, Bandit, and dependency vulnerability scanning via pip-audit / GitHub Advisory DB.
- **Orchestration:** LangGraph state machine with checkpointing, dynamic routing, and map-reduce execution.
- **Evidence Model:** Formal evidence graph linking claims to diff hunks, static tool rules, and call graph context.
- **Critic & Verification Agent:** Verification pass validating line existence, corroborating static evidence, and filtering false positives ($\ge 0.75$ confidence threshold).
- **Fault Tolerance:** Tenacity retries, exponential backoff with jitter, model fallback, schema self-correction.
- **Large PR Handling:** Trivial file filtering and AST-aware semantic decomposition (chunking).
- **GitHub Review Publisher:** Inline review comments attached to valid diff lines with optional markdown suggestions (````suggestion ... ````).
- **Persistence & Dashboard:** PostgreSQL 16 database, Redis task queue (ARQ), FastAPI backend, and React + TypeScript interactive UI with real-time SSE execution trace.
- **Scientific Evaluation:** Benchmark suite comparing the agentic system against a single-LLM baseline across Precision, Recall, F1, FPR, FNR, Defect Detection Rate, Latency, and Cost.

### 3.2 Out-of-Scope (for Initial Capstone)
- Direct mutation or autonomous git committing to the developer's branch (the system only submits review comments).
- Support for proprietary non-Git VCS (e.g., Perforce, SVN).
- Full whole-repository compilation or test execution requiring specialized build environments (e.g., executing arbitrary `npm test` or `mvn compile` inside the review worker).

---

## 4. User Personas & Use Cases

### Persona 1: Software Engineer (Pull Request Author)
- **Goal:** Receive rapid, high-signal, line-accurate feedback on security flaws, logic mistakes, and missing tests before peer review.
- **Interaction:** Opens a PR on GitHub; receives inline review comments with actionable explanations and one-click code suggestions.

### Persona 2: Tech Lead / Reviewer
- **Goal:** Reduce cognitive load during manual code review by having automated tools pre-verify basic correctness, error handling, and test adequacy.
- **Interaction:** Reads the comprehensive review summary on GitHub and inspects detailed agent reasoning traces on the web dashboard.

### Persona 3: Security & Quality Auditor
- **Goal:** Audit code changes against OWASP standards and track defect detection metrics across releases.
- **Interaction:** Explores the dashboard's analytics to evaluate system precision, static tool corroboration, and benchmark comparisons.

---

## 5. Functional Requirements (FR)

| ID | Title | Description | Priority |
|---|---|---|---|
| **FR-01** | Webhook Ingestion | Ingest `pull_request` webhook events, verify HMAC-SHA256 signatures, and deduplicate using delivery UUIDs. | MUST |
| **FR-02** | Diff & Context Extraction | Fetch unified diffs, parse hunks, extract modified files, and fetch full-file context at `head_sha`. | MUST |
| **FR-03** | Scoping & Review Planning | Analyze PR metadata and file changes to construct a `ReviewPlan` specifying active agents and focus areas. | MUST |
| **FR-04** | Security Analysis Agent | Detect OWASP Top 10 vulnerabilities, insecure coding patterns, hardcoded credentials, and CWE violations. | MUST |
| **FR-05** | Bug & Logic Agent | Detect algorithmic errors, off-by-one errors, state inconsistencies, null-dereferencing, and concurrency issues. | MUST |
| **FR-06** | Error Handling Agent | Detect swallowed exceptions (`except: pass`), resource leaks, unhandled errors, and improper cleanup logic. | MUST |
| **FR-07** | Test Analysis Agent | Identify untested code branches, missing regression tests, brittle mocks, and invalid test assertions. | MUST |
| **FR-08** | Static Analysis Pipeline | Run Semgrep, Bandit, and pip-audit inside isolated sandboxes and normalize findings into common evidence records. | MUST |
| **FR-09** | LangGraph Orchestration | Manage multi-agent workflow as a stateful graph with checkpoints, map-reduce fan-out, and failure recovery. | MUST |
| **FR-10** | Evidence Collection Model | Formally tie every candidate finding to verifiable code coordinates, static rule IDs, or AST symbol references. | MUST |
| **FR-11** | Critic & Verification Agent | Cross-check candidate findings against diff lines, prune hallucinations and pedantic nitpicks, and assign confidence scores. | MUST |
| **FR-12** | Resilient Failure Handling | Handle LLM rate limits (exponential backoff), tool crashes (graceful degradation), and schema parsing errors. | MUST |
| **FR-13** | Large PR Chunking | Decompose PRs exceeding 400 lines of code into semantic file/class chunks without splitting methods. | MUST |
| **FR-14** | Finding Schema Enforcement | Enforce strict Pydantic schema validation for all findings, ensuring consistent data representation across the pipeline. | MUST |
| **FR-15** | GitHub Review Publishing | Publish verified findings as batch PR review comments with accurate file paths, lines, and `side` markers. | MUST |
| **FR-16** | PostgreSQL Persistence | Persist repositories, PRs, review runs, evidence items, candidate findings, and verified findings. | MUST |
| **FR-17** | Redis Queue & Caching | Use Redis for asynchronous task queuing (ARQ), ephemeral agent state checkpoints, and rate-limiting. | MUST |
| **FR-18** | Web Dashboard | React + TypeScript web application with live SSE execution trace, diff visualization, and finding triage. | MUST |
| **FR-19** | Evaluation Benchmark Suite | Automated framework calculating Precision, Recall, F1, FPR, FNR, Defect Detection Rate, Latency, and Cost. | MUST |
| **FR-20** | Monolithic Baseline Comparison | Execute side-by-side benchmarking against a single-LLM reviewer to empirically validate agentic architecture advantages. | MUST |

---

## 6. Non-Functional Requirements (NFR)

### NFR-1: Reliability & Zero Hallucination Ingress
- The system must never publish an inline comment pointing to a line that was not part of the active PR diff.
- The Critic Agent must enforce a minimum calibrated confidence score of **0.75** before publication.

### NFR-2: Performance & Review Latency
- Standard PRs ($\le 300$ lines of code changed) must complete analysis and comment submission within **90 seconds**.
- Large PRs ($300 - 1500$ lines of code changed) must complete review within **180 seconds**.

### NFR-3: Cost Efficiency & Token Optimization
- Trivial files (lockfiles, minified bundles, pure markdown docs) must be pruned before agent dispatch.
- Average LLM API expenditure must not exceed **$0.15 per standard PR review**.

### NFR-4: Security & Isolation
- All static analysis tools must execute in unprivileged, read-only mounted, network-disabled containers.
- Untrusted user input from PR diffs and commit messages must be isolated using strict XML tags in prompts to mitigate prompt injection.

### NFR-5: Modularity & Code Quality
- Zero business logic inside FastAPI route handlers.
- Modular Python codebase adhering to PEP 8, formatted with Black/Ruff, and strictly typed with Mypy.
- Test coverage must exceed **80%** across core graph, diff parsing, and verification modules.

---

## 7. Acceptance Criteria & Measurable KPIs

| Metric | Target Value | Baseline Expectation (Single LLM) | Validation Method |
|---|---|---|---|
| **Precision** | $\ge 85\%$ | $\sim 55\% - 65\%$ | Labeled benchmark ground-truth test suite |
| **False Positive Rate (FPR)** | $\le 15\%$ | $\ge 35\%$ | Labeled benchmark ground-truth test suite |
| **Recall on Security Flaws** | $\ge 80\%$ | $\sim 60\%$ | Injection of known CVE patterns (Bandit/Semgrep corroboration) |
| **Line Mapping Accuracy** | $100\%$ | $\sim 70\%$ | GitHub API 422 error rate must be $0\%$ |
| **System Uptime / Availability** | $99.5\%$ | N/A | Uptime monitoring on FastAPI backend |

---

## 8. Technical Constraints
- **Python Version:** 3.11+ (leveraging native `asyncio` task groups and performance optimizations).
- **PostgreSQL Version:** 16+ (relational integrity, JSONB indexing).
- **Redis Version:** 7+ (Redis streams, ephemeral caching, ARQ task broker).
- **Node.js / React:** Node 20+, React 18+, TypeScript 5+, Vite build tool.
- **GitHub API Limits:** Max 5,000 requests/hour per installation; batch review submission must be utilized.
