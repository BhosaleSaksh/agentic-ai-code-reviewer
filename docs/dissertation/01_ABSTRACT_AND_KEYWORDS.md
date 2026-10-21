# Chapter 1: Abstract and Keywords

**Project Title:** An Agentic AI Framework for Reliable and Evidence-Based Automated Code Review  
**Author:** Saksham Bhosale  
**Repository:** `D:\Projects\agentic-code-reviewer`  
**Execution Branch:** `feat/phase-7-evaluation`  

---

## 1. Abstract

Modern software engineering relies extensively on peer code review to identify defects, enforce architectural patterns, and maintain code quality before integration into production branches. However, manual code review is cognitively demanding, time-consuming, and represents a significant development bottleneck. While traditional static program analysis tools offer deterministic verification, they suffer from high false positive rates, rigid heuristics, and an inability to understand developer intent or multi-file architectural semantics. Conversely, recent attempts to automate code review using monolithic, single-prompt Large Language Models (LLMs) suffer from severe unreliability: they frequently hallucinate non-existent security vulnerabilities, invent invalid syntax rules, generate vague stylistic critiques, and fail to provide verifiable line-anchored evidence, culminating in severe developer alert fatigue.

To resolve this fundamental dichotomy between deterministic rigidity and generative hallucination, this dissertation proposes, designs, and evaluates an **Agentic AI Framework for Reliable and Evidence-Based Automated Code Review**. The framework departs from unconstrained generative review by orchestrating a structured, stateful multi-agent workflow grounded in deterministic evidence. The architecture integrates four complementary subsystems:
1. **Deterministic Static Analysis Pipeline:** Executes AST-level security linters (Bandit), rule-based semantic analyzers (Semgrep), and dependency vulnerability checkers (Pip-Audit) within isolated execution containers to extract verifiable static evidence.
2. **Context-Aware Dynamic Planner:** Parses unified pull request diffs, resolves precise lexical AST line intervals, and dynamically determines the review scope and agent routing plan.
3. **Specialized Specialist Agents:** Deploys fine-grained specialist review agents across distinct defect domains (Security, Bug Logic, Error Handling, and Test Adequacy) executing in parallel with bounded context.
4. **Evidence Grounding Engine & Adversarial Critic Agent:** Cross-references candidate findings against deterministic tool outputs and modified diff hunks. An adversarial LLM critic inspects every candidate finding against a strict verification rubric, rejecting ungrounded assumptions, speculative assertions, and unanchored remarks prior to publication.

We empirically evaluate the proposed framework against four comparative baselines across a curated 23-case evaluation corpus comprising 18 synthetic defect benchmarks and 5 real-world open-source pull requests drawn from widely used repositories (`requests-toolbelt`, `urllib3`, `bottle`, `flask`). In local testing using the `qwen3:4b-instruct` model via Ollama, the single-LLM baseline produced 56 false positives out of 70 total reported findings, yielding a prohibitive False Discovery Rate ($\text{FDR} = \frac{\text{FP}}{\text{TP} + \text{FP}}$) of **$80.0\%$** and an F1-score of **$0.3011$**. In contrast, the full agentic framework achieved **$0.0\%$ False Discovery Rate** ($\text{FP} = 0, \text{TP} = 22$) and an F1-score of **$0.9778$**, representing a **$100.0\%$ relative reduction in false discovery rate**. Ablation experiments confirm that while the uncurated specialist agents identify 23 defects, they generate 57 false positives ($\text{FDR} = 71.25\%$); the adversarial critic successfully purges all 57 false positives with a minimal trade-off of dropping a single subtle true positive defect (`REAL-TEST-001`). On the 5 real-world pull requests, the framework maintained $100\%$ precision ($\text{FDR} = 0.0\%$), outperforming the single-LLM baseline ($\text{FDR} = 81.25\%$). These findings demonstrate that multi-agent specialization paired with deterministic evidence grounding establishes a robust paradigm for automated, reliable software peer review.

---

## 2. Keywords

* **ACM Computing Classification System (CCS):**
  * *Software and its engineering* $\rightarrow$ Software creation and management $\rightarrow$ Software verification and validation $\rightarrow$ Software defect analysis
  * *Computing methodologies* $\rightarrow$ Artificial intelligence $\rightarrow$ Distributed artificial intelligence $\rightarrow$ Multi-agent systems
  * *Computing methodologies* $\rightarrow$ Natural language processing $\rightarrow$ Language models
  * *Security and privacy* $\rightarrow$ Software and application security $\rightarrow$ Software security engineering
* **IEEE Keywords:**
  * Automated Code Review; Multi-Agent Systems; Large Language Models; Static Analysis; Program Verification; False Discovery Rate; Evidence Grounding; Software Quality Assurance; DevSecOps.

---

## 3. Executive Quantitative Summary

The following metrics summarize the validated performance of the five evaluated baselines across the complete 23-case benchmark:

| Metric / Baseline | Static Analysis Only | Single-LLM Reviewer | Agentic (No Static Evidence) | Agentic (No Critic) | Full Agentic Framework |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Run Identifier** | `e130978a` | `a1f820b7` | `d56531a3` | `80467945` | `3b8d2539` |
| **Evaluated Cases** | 23 | 23 | 23 | 23 | 23 |
| **Ground Truth Defects** | 23 | 23 | 23 | 23 | 23 |
| **Candidate Predictions** | 5 | 70 | 19 | 80 | 22 |
| **True Positives (TP)** | 5 | 14 | 19 | 23 | **22** |
| **False Positives (FP)** | 0 | 56 | 0 | 57 | **0** |
| **False Negatives (FN)** | 18 | 9 | 4 | 0 | **1** |
| **Precision** | 1.0000 | 0.2000 | 1.0000 | 0.2875 | **1.0000** |
| **Recall** | 0.2174 | 0.6087 | 0.8261 | 1.0000 | **0.9565** |
| **F1-Score** | 0.3572 | 0.3011 | 0.9048 | 0.4466 | **0.9778** |
| **False Discovery Rate (FDR)** | 0.0000 | 0.8000 | 0.0000 | 0.7125 | **0.0000** |
| **Relative FDR Reduction vs Single-LLM** | — | Baseline | 100.0% | 10.9% | **100.0%** |
| **Total Telemetry Tokens** | 0 | 11,434 | 61,930 | 34,500 | 74,500 |
| **Execution Cost (USD)** | $0.00 | $0.00 | $0.00 | $0.00 | $0.00 |

*Note: All runs executed in real mode utilizing local Ollama `qwen3:4b-instruct` on dedicated infrastructure.*
