# An Agentic AI Framework for Reliable and Evidence-Based Automated Code Review

## Master Dissertation Document & Chapter Guide

**Author:** Saksham Bhosale  
**Degree:** Bachelor of Technology / Bachelor of Engineering in Computer Science and Engineering  
**Project Repository:** `D:\Projects\agentic-code-reviewer`  
**Execution Branch:** `feat/phase-7-evaluation`  
**Evaluation Model Target:** `qwen3:4b-instruct` (Ollama 0.40.4 Local Inference)  
**Date of Verification:** October 2026  

---

## Abstract Overview

Automated code review has emerged as a critical frontier in artificial intelligence for software engineering (AI4SE). While modern Large Language Models (LLMs) demonstrate impressive fluency in interpreting code diffs, conventional single-prompt LLM reviewers exhibit unacceptably high rates of hallucinated defects and ungrounded stylistic nitpicks, resulting in developer alert fatigue and high False Discovery Rates (FDR). Conversely, deterministic static analysis tools (e.g., Bandit, Semgrep, Pip-Audit) offer mathematically grounded precision but suffer from high false negative rates and lack semantic context.

This dissertation presents the design, formalization, implementation, and empirical validation of an **Agentic AI Framework for Reliable and Evidence-Based Automated Code Review**. By combining deterministic static analysis evidence with a stateful multi-agent LangGraph workflow—comprising a Planner Agent, specialized Domain Specialists (Security, Bug Logic, Error Handling, Test Adequacy), an Evidence Grounding Engine, and an Adversarial Critic Agent—the framework enforces strict structural verification invariants before candidate review comments can be published.

Evaluating the architecture against five rigorous baseline configurations across a 23-case benchmark corpus (18 synthetic defect benchmarks and 5 real-world open-source pull requests), our empirical results demonstrate:
1. **False Discovery Rate Elimination:** Reduction of finding-level False Discovery Rate ($\text{FDR} = \frac{\text{FP}}{\text{TP} + \text{FP}}$) from **$80.0\%$** in the single-LLM baseline down to **$0.0\%$** in the full agentic system, achieving a **$100.0\%$ relative FDR reduction**.
2. **Adversarial Critic Trade-off:** The Critic Agent eliminates 57 false positive candidate findings present in the uncurated specialist output, with a trade-off of dropping a single subtle true positive defect (`REAL-TEST-001`), achieving an overall Recall of **$95.65\%$** and an F1-score of **$0.9778$** (compared to $0.3011$ for the single-LLM reviewer).
3. **Real-World Generalization:** On 5 production pull requests from prominent open-source Python repositories (`requests-toolbelt`, `urllib3`, `bottle`, `flask`), the agentic framework achieved $100\%$ precision ($\text{FDR} = 0.0\%$), while the single-LLM baseline suffered an $\text{FDR}$ of $81.25\%$ (13 false positives).

---

## Dissertation Table of Contents

The complete dissertation is organized into the following self-contained chapters and technical appendices:

1. **[`01_ABSTRACT_AND_KEYWORDS.md`](file:///D:/Projects/agentic-code-reviewer/docs/dissertation/01_ABSTRACT_AND_KEYWORDS.md)**
   * Formal academic abstract
   * Structured keywords (ACM / IEEE taxonomy)
   * Key quantitative findings summary
2. **[`02_INTRODUCTION.md`](file:///D:/Projects/agentic-code-reviewer/docs/dissertation/02_INTRODUCTION.md)**
   * Background and industrial context of modern peer code review
   * Failure modes of static analyzers and monolithic LLM reviewers
   * Motivation for evidence-grounded agentic verification
   * Research questions (RQ1 through RQ4)
   * Primary scientific and engineering contributions
3. **[`03_LITERATURE_REVIEW.md`](file:///D:/Projects/agentic-code-reviewer/docs/dissertation/03_LITERATURE_REVIEW.md)**
   * Foundations of code review in software engineering
   * Static program analysis: benefits, limits, and developer adoption hurdles
   * Large language models in software engineering (AI4SE)
   * Multi-agent architectures, role specialization, and reflection patterns
   * Hallucination mitigation and grounded verification
   * Benchmark datasets and reproducibility standards
4. **[`04_PROBLEM_STATEMENT_AND_OBJECTIVES.md`](file:///D:/Projects/agentic-code-reviewer/docs/dissertation/04_PROBLEM_STATEMENT_AND_OBJECTIVES.md)**
   * Formal problem formulation
   * The Alert Fatigue Dilemma
   * Project goals and measurable success criteria
   * Mathematical definitions of evaluation metrics (Precision, Recall, F1, FDR)
5. **[`05_SYSTEM_DESIGN_AND_METHODOLOGY.md`](file:///D:/Projects/agentic-code-reviewer/docs/dissertation/05_SYSTEM_DESIGN_AND_METHODOLOGY.md)**
   * Architectural overview and modular decomposition
   * Unified diff parsing and AST lexical coordinate resolution
   * Deterministic static analysis pipeline (Bandit, Semgrep, Pip-Audit)
   * Dynamic planner and specialist agent fan-out
   * Evidence grounding service and bidirectional anchoring
   * Adversarial critic agent and publication safety invariants
6. **[`06_IMPLEMENTATION.md`](file:///D:/Projects/agentic-code-reviewer/docs/dissertation/06_IMPLEMENTATION.md)**
   * Technology stack (Python 3.12, FastAPI, LangGraph, Pydantic v2, PostgreSQL, Redis, ARQ)
   * Local LLM provider integration with Ollama (`qwen3:4b-instruct`)
   * Worker task pipeline and asynchronous job lifecycle
   * GitHub App authentication and multi-tiered publication safety gates
   * Automated verification test suite and code coverage analysis
7. **[`07_EXPERIMENTAL_SETUP_AND_RESULTS.md`](file:///D:/Projects/agentic-code-reviewer/docs/dissertation/07_EXPERIMENTAL_SETUP_AND_RESULTS.md)**
   * Benchmark corpus composition (18 synthetic + 5 real-world PRs)
   * Baseline configurations (Static Analysis Only, Single-LLM, Agentic No Static Evidence, Agentic No Critic, Agentic Full)
   * Empirical performance results and comprehensive comparison tables
   * Category-specific performance breakdown
   * Detailed ablation study (analyzing static evidence and critic filtering)
   * Real-world pull request evaluation
   * Resource telemetry (tokens, API calls, latency measurements)
8. **[`08_DISCUSSION_LIMITATIONS_AND_THREATS.md`](file:///D:/Projects/agentic-code-reviewer/docs/dissertation/08_DISCUSSION_LIMITATIONS_AND_THREATS.md)**
   * In-depth interpretation of experimental results
   * Analysis of the single missed defect (`REAL-TEST-001`)
   * The Critic trade-off: false positive suppression vs. conservative filtering
   * Execution latency and computational boundaries
   * Threats to internal, external, construct, and conclusion validity
9. **[`09_CONCLUSION_AND_FUTURE_WORK.md`](file:///D:/Projects/agentic-code-reviewer/docs/dissertation/09_CONCLUSION_AND_FUTURE_WORK.md)**
   * Summary of completed work and primary conclusions
   * Open research directions and roadmap:
     - Cross-repository Retrieval-Augmented Generation (RAG)
     - Historical bug knowledge integration
     - Multi-lingual diff parsing and semantic symbol graphing
     - Model scaling across diverse open-weights and commercial providers
10. **[`10_REFERENCES.md`](file:///D:/Projects/agentic-code-reviewer/docs/dissertation/10_REFERENCES.md)**
    * Complete, verified academic bibliography with formal citations and DOIs
11. **[`11_FIGURES_AND_TABLES_PLAN.md`](file:///D:/Projects/agentic-code-reviewer/docs/dissertation/11_FIGURES_AND_TABLES_PLAN.md)**
    * Complete catalog of architectural diagrams, sequence charts, and benchmark tables
    * Renderable Mermaid.js source diagrams and structural specifications

---

## Reproducibility Verification Summary

All empirical data reported across this dissertation are derived from committed, immutable test runs frozen in the project repository:
* **Commit A (`31f1dc8`):** `feat(llm): add local Ollama provider, timeout fallback, and publication safety gates`
* **Commit B (`4a6a5a0`):** `feat(eval): integrate Ollama into baseline harness and update cost telemetry`
* **Commit C (`7ed2399`):** `docs(eval): record empirical benchmark reports and reproducibility artifacts`

The raw evaluation run directories (`evaluation/results/<run-id>/`) contain per-case raw execution records (`cases.json`), configuration snapshots (`config.json`), and metrics summaries (`summary.json`, `metrics.csv`), ensuring full academic and experimental auditability.
