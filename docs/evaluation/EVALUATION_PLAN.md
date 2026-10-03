# Empirical Evaluation Plan & Benchmarking Architecture

**Project:** Agentic AI Framework for Reliable and Evidence-Based Automated Code Review  
**Milestone:** Phase 7 — Evaluation, Benchmarking & Data Provenance  
**Date:** 2026-10-03  

---

## 1. Overview and Objectives

The objective of Phase 7 is to establish a rigorous, reproducible, and scientifically grounded empirical evaluation framework. This framework evaluates the code review capabilities of the Agentic AI Code Reviewer against classical static analysis tools and non-agentic single-prompt LLM baselines.

Crucially, **the evaluation system does not train or fine-tune machine learning models**. Instead, it benchmarks reviewer architectures against an authoritative, versioned corpus of controlled synthetic test cases and curated open-source pull requests.

---

## 2. Research Questions (RQs)

The benchmark is designed to answer five primary research questions:

- **RQ1 (Defect Detection Complementarity):** Does the multi-agent specialist architecture detect subtle domain defects (logic edge cases, state transitions, unhandled timeouts) that a monolithic single-LLM reviewer overlooks?
- **RQ2 (Evidence Grounding Precision):** Does corroborating candidate findings with AST parsing, dataflow tracing, and containerized static analysis tools improve finding precision and reduce ungrounded assertions?
- **RQ3 (Critic False-Positive Suppression):** Does the Critic verification node systematically identify and reject speculative hallucinations and low-severity noise, reducing developer alert fatigue?
- **RQ4 (Comparative Architecture Analysis):** How does the agentic architecture compare with static-analysis-only tools (Bandit, Semgrep) and monolithic single-LLM reviewers across precision, recall, and F1 score?
- **RQ5 (Computational Cost & Latency Trade-Off):** What are the computational overheads, API call volumes, token usage, and dollar costs associated with multi-agent orchestration versus single-shot models?

---

## 3. Evaluation Corpus Architecture

The evaluation dataset resides in `evaluation/datasets/` and is divided into two corpora:

### 3.1. Controlled Synthetic Benchmark (`evaluation/datasets/synthetic/`)
Designed with ground-truth isolation to test specific vulnerability and bug patterns across four canonical categories:
1. **`SECURITY`**: SQL injection, hardcoded secrets, unsafe deserialization (pickle), broken cryptographic hashes (MD5), and command injection (subprocess `shell=True`).
2. **`BUG_LOGIC`**: Off-by-one boundary conditions, unchecked NoneType attribute dereferencing, inverted boolean conditions, invalid state machine transitions, and operator precedence errors.
3. **`ERROR_HANDLING`**: Swallowed exceptions with bare `pass`, unhandled network timeouts, unclosed file resource leaks, mismatched exception type catching, and fail-open fallback privilege escalations.
4. **`TEST_ADEQUACY`**: Untested new feature branches, insufficient boundary coverage (zero/negative values), and unverified retry delay regression risks.

### 3.2. Real-World OSS Pull Requests (`evaluation/datasets/manifests/real_world_manifest.json`)
A curated manifest of pull requests from widely used open-source repositories (`psf/requests`, `pallets/flask`, `tiangolo/fastapi`, `celery/celery`, `urllib3/urllib3`) with maintainer-verified CVE advisories or merged bugfix commits.

---

## 4. Evaluation Workflow & Leakage Controls

To guarantee scientific validity, the evaluation harness enforces strict information barriers:
1. **Prompt Isolation:** Model prompts receive **strictly** the code snippet / diff under review, the affected file path, and a high-level PR description.
2. **Out-of-Band Ground Truth:** Defect descriptions, expected rule IDs, exact line ranges, and severity expectations are loaded separately into the matching layer and are never concatenated into reviewer prompt contexts.
3. **Deterministic Bipartite Matching:** Predicted findings are paired to ground-truth defects using file path matching, a 5-line coordinate proximity tolerance, category compatibility verification, and greedy assignment.
4. **Duplicate Penalization:** If a reviewer emits multiple findings pointing to the same single defect, only the first finding receives a True Positive credit; subsequent predictions are marked as redundant false positives.

---

## 5. Reviewer Baselines and Ablation Matrix

The framework evaluates five distinct reviewer configurations:
1. **Baseline 1 (`static_analysis_only`):** Deterministic tool heuristics (Bandit, Semgrep, flake8-bugbear) without LLM reasoning.
2. **Baseline 2 (`single_llm_reviewer`):** A single LLM prompted monolithically with the full diff context without specialist decomposition.
3. **Baseline 3 (`agentic_critic_full`):** The complete production pipeline: Planner $\to$ Specialists fan-out $\to$ Evidence grounding $\to$ Critic verification.
4. **Ablation 1 (`agentic_no_critic`):** Multi-agent specialists generate candidate findings, but the Critic verification node is omitted.
5. **Ablation 2 (`agentic_no_static_evidence`):** Multi-agent specialists and Critic run without access to static analysis tool outputs.

---

## 6. Reproducibility & Output Artifacts

Every benchmark run generates:
- A unique run UUID (`run_id`)
- Git commit SHA snapshot
- Machine-readable JSON output: `evaluation/results/{run_id}_{baseline}.json`
- Tabular CSV summary: `evaluation/results/{run_id}_{baseline}_summary.csv`
- Complete confusion matrix, metric percentages, Wilson confidence intervals, and token/cost telemetry.
