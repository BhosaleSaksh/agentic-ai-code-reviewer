# Evaluation & Benchmarking Framework

This directory houses the reproducible empirical evaluation framework for the **Agentic AI Code Reviewer**. It provides versioned datasets, baseline reviewer implementations, deterministic finding matching, and automated metric calculation.

---

## Directory Structure

```text
evaluation/
├── datasets/
│   ├── manifest.json                  # Authoritative dataset version manifest
│   ├── manifests/
│   │   ├── real_world_manifest.json   # Real-world OSS PR benchmark manifest
│   ├── synthetic/
│   │   ├── security/                  # Synthetic security vulnerability cases
│   │   ├── bug_logic/                 # Synthetic bug/logic error cases
│   │   ├── error_handling/            # Synthetic error handling mistake cases
│   │   └── test_adequacy/             # Synthetic test coverage inadequacy cases
│   └── real_world/                    # Real-world repository diffs
├── models/
│   ├── case.py                        # EvaluationCase and GroundTruthDefect schemas
│   ├── finding.py                     # NormalizedFinding and MatchResult schemas
│   ├── metrics.py                     # BenchmarkMetrics and ResourceUsage schemas
│   └── result.py                      # BenchmarkRunResult and case outcome schemas
├── matching/
│   └── matcher.py                     # Deterministic finding matcher (5-line tolerance)
├── metrics/
│   └── calculator.py                  # Precision, Recall, F1, and Wilson CI calculator
├── baselines/
│   ├── base.py                        # BaseBaseline interface
│   ├── static_analysis.py             # Baseline 1: Static analysis only
│   ├── single_llm.py                  # Baseline 2: Single-LLM reviewer
│   ├── agentic.py                     # Baseline 3: Full Agentic Reviewer (Planner+Specialists+Critic)
│   └── ablation.py                    # Ablation configurations (No-Critic, No-Evidence)
├── runner.py                          # Benchmark runner orchestrating evaluation runs
├── scripts/
│   └── run_benchmark.py               # CLI runner script for automated evaluation
└── results/                           # JSON and CSV output reports from benchmark runs
```

---

## Running the Benchmark

### 1. Run all baselines across all benchmark categories
```bash
python evaluation/scripts/run_benchmark.py --baseline all --category all
```

### 2. Run a specific baseline against a specific category
```bash
python evaluation/scripts/run_benchmark.py --baseline agentic --category security
```

Supported `--baseline` arguments:
- `all` (runs all baselines and generates a comparative markdown table)
- `agentic` (Full Agentic + Critic pipeline)
- `single_llm` (Monolithic single-shot LLM reviewer)
- `static_only` (Pure static analysis: Bandit/Semgrep)
- `ablation_no_critic` (Agentic pipeline without Critic verification)
- `ablation_no_static` (Agentic pipeline without static evidence grounding)

Supported `--category` arguments:
- `all` (all 18 synthetic cases)
- `security` (5 cases)
- `bug_logic` (5 cases)
- `error_handling` (5 cases)
- `test_adequacy` (3 cases)

---

## Benchmark Metrics Output

Each benchmark run writes machine-readable reports to `evaluation/results/`:
- `{run_id}_{baseline}.json`: Full case-level findings, match results, and telemetry.
- `{run_id}_{baseline}_summary.csv`: Tabular CSV row ready for statistical aggregation and plotting.

Metrics calculated:
- **True Positives ($TP$), False Positives ($FP$), False Negatives ($FN$)**
- **Precision, Recall, $F_1$-Score**
- **Wilson Score 95% Confidence Intervals** for Precision and Recall
- **False Positive Rate ($FPR$) and False Negative Rate ($FNR$)**
- **Latency, Token Usage (Prompt & Completion), and Estimated API Cost ($USD)**
- **Verification and Grounding Rates**
