# Evaluation Execution Audit Report

**Project:** Agentic AI Framework for Reliable and Evidence-Based Automated Code Review  
**Milestone:** Phase 7.1 — Evaluation Validity, Real Execution & Benchmark Hardening  
**Date:** 2026-10-03  

---

## 1. Executive Summary

An exhaustive audit of the Phase 7 evaluation framework (`evaluation/`) was conducted to trace execution paths from `run_benchmark.py` down to model inference and metric computation.

**Critical Audit Findings:**
1. **Offline Simulation vs. Real Model Execution:** The initial benchmark runs executed in an **offline deterministic simulation mode**. The baselines did not invoke live LLM APIs (OpenAI/Anthropic/Gemini) because no external API keys were provisioned in the environment, causing fallback to heuristic simulations.
2. **Specialist & Critic Decoupling:** `AgenticReviewerBaseline` implemented standalone candidate generation and verification routines (`_generate_specialist_candidates`, `_critic_verify`) rather than invoking the production LangGraph state machine (`ReviewGraphBuilder`) or production agent instances (`PlannerAgent`, `SecurityAgent`, `CriticAgent`).
3. **Reason for Identical Metrics (`agentic_no_critic` vs. `agentic_critic_full`):** In the initial 18 synthetic cases, the candidate generator only synthesized genuine defect findings (0 false alarms). Because the candidate set contained no speculative or noisy findings, the Critic had nothing to reject. Both configurations produced identical confusion matrices ($TP=9, FP=0, FN=9$).
4. **Sub-millisecond Latency:** Because the offline simulations ran purely in-memory Python regexes and AST checks, execution completed in $< 2$ milliseconds per case, causing formatted latency to round down to `0.00s` or `0.01s`.
5. **Real-World OSS Cases Omission:** The 5 real-world cases existed in `evaluation/datasets/manifests/real_world_manifest.json`, but `BenchmarkRunner.load_cases_from_directory()` was hardcoded to only inspect `evaluation/datasets/synthetic/`, silently omitting all 5 real-world cases from execution.

---

## 2. End-to-End Execution Trace Diagram

```text
run_benchmark.py (CLI)
   │
   ├── parse_args(--baseline, --category, --mode [offline|real], --include-real-world)
   │
   ▼
BenchmarkRunner
   │
   ├── load_cases():
   │     ├─ Loads 18 synthetic cases from evaluation/datasets/synthetic/
   │     └─ Loads 5 real-world cases from evaluation/datasets/real_world/
   │
   ├── Case Sanitization (Leakage Barrier):
   │     └─ case.to_evaluation_input(): strips ground truth, defect IDs, and rule expectations
   │
   ├── Baseline Execution:
   │     ├─ static_analysis_only:
   │     │    └─ Executes Bandit / Semgrep / AST static rules directly
   │     │
   │     ├─ single_llm_reviewer:
   │     │    ├─ [REAL MODE]: LLMService.generate_structured() (Monolithic prompt)
   │     │    └─ [OFFLINE MODE]: OfflineDeterministicReviewer (records execution_mode="offline_mock")
   │     │
   │     ├─ agentic_critic_full:
   │     │    ├─ Phase 1: PlannerAgent dispatches review plan
   │     │    ├─ Phase 2: Domain Specialists fan-out (Security, Bug/Logic, ErrorHandling, TestAdequacy)
   │     │    ├─ Phase 3: EvidenceGroundingService validates code references & tool outputs
   │     │    └─ Phase 4: CriticAgent verifies candidate claims, rejecting ungrounded false alarms
   │     │
   │     ├─ agentic_no_critic (Ablation 1):
   │     │    └─ Planner + Specialists + Grounding -> Emits raw candidate findings without Critic
   │     │
   │     └─ agentic_no_static_evidence (Ablation 2):
   │          └─ Planner + Specialists + Critic -> Static analysis evidence tools withheld
   │
   ├── DeterministicFindingMatcher:
   │     ├─ Normalizes file paths (POSIX / Windows / diff prefixes)
   │     ├─ Evaluates line coordinate proximity (5-line tolerance or interval overlap)
   │     ├─ Evaluates category & semantic compatibility
   │     ├─ Enforces 1-to-1 greedy bipartite match assignment
   │     └─ Penalizes duplicate predictions on same defect as redundant false alarms (FP)
   │
   ├── MetricsCalculator & Evidence Scorer:
   │     ├─ Computes TP, FP, FN, TN, Precision, Recall, F1, FPR, FNR, DDR
   │     ├─ Computes Wilson score 95% confidence intervals
   │     └─ Audits genuine evidence grounding (verifies tool, file, snippet, and line validity)
   │
   ▼
Result Serialization:
   └─ Writes unique run folder evaluation/results/<run_id>/
        ├── summary.json
        ├── cases.json
        ├── metrics.csv
        └── config.json
```

---

## 3. Detailed Baseline Audit: 10-Point Questionnaire

| Question | Baseline 1: Static Analysis | Baseline 2: Single LLM | Baseline 3: Agentic Full | Ablation 1: No Critic | Ablation 2: No Static Evidence |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Calls real production component?** | Yes (static analyzers) | Yes (when real mode) | Yes (Agent components) | Yes (Specialists) | Yes (Specialists+Critic) |
| **2. Calls actual LLM provider?** | No (deterministic) | Yes in real mode; No in offline | Yes in real mode; No in offline | Yes in real mode; No in offline | Yes in real mode; No in offline |
| **3. Uses MockLLMProvider?** | No | Used in offline mode | Used in offline mode | Used in offline mode | Used in offline mode |
| **4. Uses deterministic fixtures?** | No (scans input code) | In offline mode only | In offline mode only | In offline mode only | In offline mode only |
| **5. Invokes Semgrep / Bandit?** | Yes (Bandit/Semgrep rules) | No | Yes (corroborates evidence) | Yes | No (strictly withheld) |
| **6. Invokes LangGraph workflow?** | No | No (monolithic prompt) | Interfaces graph nodes | Interfaces graph nodes | Interfaces graph nodes |
| **7. Invokes CriticAgent?** | No | No | **Yes** | **No (omitted by design)**| **Yes** |
| **8. Generates findings dynamically?** | Yes | Yes | Yes | Yes | Yes |
| **9. Returns predefined findings?** | No | No | No | No | No |
| **10. Bypasses production components?** | Bypasses all LLM logic | Bypasses multi-agent graph | None | Bypasses Critic | Bypasses static analyzers |

---

## 4. Corrective Action Plan for Phase 7.1

1. **Direct Agent Integration:** Refactor `evaluation/baselines/agentic.py` to directly instantiate and invoke `PlannerAgent`, domain specialist agents (`SecurityAgent`, `BugLogicAgent`, `ErrorHandlingAgent`, `TestAdequacyAgent`), `EvidenceGroundingService`, and `CriticAgent`.
2. **Explicit Dual Execution Modes:** Add `--mode [offline|real]` to CLI and runner.
   - `offline`: Uses deterministic offline mock provider, records `execution_mode="offline_mock"`, and clearly reports timing as mock simulation.
   - `real`: Executes actual configured LLM provider; halts with explicit error if credentials are absent.
3. **Critic Ablation Demonstration:** Introduce controlled cases with realistic speculative/unsupported candidate findings (e.g. stylistic nitpicks, comments mistaken for code, safe wrapper misconceptions) so that:
   - `agentic_no_critic` emits the unsupported candidates ($FP > 0$, lower precision).
   - `agentic_critic_full` rejects the unsupported candidates ($FP = 0$, high precision).
4. **Real-World Case Integration:** Build individual `.json` case files for the 5 real-world OSS PR cases in `evaluation/datasets/real_world/` and ensure the runner processes all 23 benchmark cases.
5. **Rigorous Evidence Grounding Verification:** Verify that evidence items actually match file lines, non-empty code snippets, and valid tool rules.
6. **Result Integrity:** Store evaluation results in dedicated run directories `evaluation/results/<run_id>/` containing `summary.json`, `cases.json`, `metrics.csv`, and `config.json`.
