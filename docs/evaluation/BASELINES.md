# Reviewer Baselines & Ablation Study Architecture

**Project:** Agentic AI Framework for Reliable and Evidence-Based Automated Code Review  
**Milestone:** Phase 7 — Evaluation, Benchmarking & Data Provenance  
**Date:** 2026-10-03  

---

## 1. Overview of Experimental Configurations

To evaluate the contributions of specialist agents, evidence grounding, and verification, the evaluation framework implements three core baselines and two ablation configurations:

```
                            [Evaluation Case Input]
                                      │
        ┌──────────────┬──────────────┼──────────────┬──────────────┐
        ▼              ▼              ▼              ▼              ▼
   [Baseline 1]   [Baseline 2]   [Ablation 1]   [Ablation 2]   [Baseline 3]
  Static Analysis   Single-LLM      Agentic        Agentic        Agentic
       Only          Monolith      No-Critic     No-Evidence    Full Pipeline
        │              │              │              │              │
        ▼              ▼              ▼              ▼              ▼
   [Normalized]   [Normalized]   [Candidate]    [Normalized]   [Verified]
     Findings       Findings       Findings       Findings      Findings
        └──────────────┴──────────────┼──────────────┴──────────────┘
                                      ▼
                      [Deterministic Finding Matcher]
                                      ▼
                       [Metrics & Statistical Report]
```

---

## 2. Baseline Definitions

### Baseline 1: Static Analysis Only (`static_analysis_only`)
- **Architecture:** Executes deterministic static analyzers (Bandit, Semgrep, flake8-bugbear) against the source code without invoking any language model.
- **Strengths:** Zero token cost, sub-second latency ($< 0.05$s), 100% deterministic reproducibility.
- **Weaknesses:** Blind to high-level domain bugs (state transitions, inverted logic conditions, missing test coverage, business logic boundary errors).

### Baseline 2: Single-LLM Reviewer (`single_llm_reviewer`)
- **Architecture:** Submits the complete file diff and PR context to a single general-purpose LLM prompt in one monolithic call, requesting structured JSON finding outputs.
- **Strengths:** Single API call overhead, capable of identifying both security and logic bugs.
- **Weaknesses:** High susceptibility to alert noise, hallucinations, inconsistent line anchoring, and lack of external static analysis grounding.

### Baseline 3: Full Agentic Reviewer (`agentic_critic_full`)
- **Architecture:** Production multi-agent pipeline:
  1. **Planner Agent:** Analyzes diff scope and dispatches specialized domain tasks.
  2. **Domain Specialists:** Parallel fan-out across Security, Bug/Logic, Error Handling, and Test Adequacy agents.
  3. **Evidence Grounding Service:** Corroborates candidate findings with Bandit/Semgrep static analysis outputs and AST snippets.
  4. **Critic Verification Node:** Verifies evidence sufficiency, suppresses hallucinations, and rejects low-severity stylistic nitpicks.
- **Strengths:** High precision, evidence grounded, robust against false alarms.
- **Weaknesses:** Higher latency and token cost due to multi-agent fan-out and verification rounds.

---

## 3. Ablation Studies

### Ablation 1: Agentic Without Critic (`agentic_no_critic`)
- **Objective:** Quantify the exact false-positive reduction contributed by the Critic Agent.
- **Configuration:** Executes Planner and Specialists with Evidence Grounding, but directly emits all raw candidate findings without verification filtering.
- **Hypothesis:** Recall remains high, but precision drops significantly due to unverified candidate assertions.

### Ablation 2: Agentic Without Static Evidence (`agentic_no_static_evidence`)
- **Objective:** Measure the importance of empirical static analysis grounding in code review.
- **Configuration:** Runs Planner, Specialists, and Critic, but withholds static analysis tool outputs (`evidence_items = []`).
- **Hypothesis:** Reviewer precision declines on syntax-verifiable vulnerabilities (e.g. SQL injection, unclosed resources, broken hashes) when static corroboration is absent.
