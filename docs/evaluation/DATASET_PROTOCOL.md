# Dataset Curation Protocol & Ground-Truth Governance

**Project:** Agentic AI Framework for Reliable and Evidence-Based Automated Code Review  
**Milestone:** Phase 7 — Evaluation, Benchmarking & Data Provenance  
**Date:** 2026-10-03  

---

## 1. Benchmark Taxonomy and Defect Categories

The benchmark corpus categorizes code defects across four domains:

| Category | Sub-Types Tested | Authoritative Ground-Truth Sources |
| :--- | :--- | :--- |
| **`SECURITY`** | SQL Injection, Hardcoded Secrets, Unsafe Deserialization, Broken Cryptographic Hash, Command Injection | Bandit Rules (B608, B105, B301, B303, B602), CWE Taxonomy, Semgrep Registry |
| **`BUG_LOGIC`** | Boundary Errors (Off-by-One), Null/None Dereferencing, Inverted Condition Polarity, State Machine Invariant Violations, Arithmetic Precedence Errors | AST Path Invariants, Mypy Strict Null Checks, Unit Assertion Regressions |
| **`ERROR_HANDLING`** | Swallowed Exceptions (`except: pass`), Missing Network Timeout, Resource Descriptor Leaks, Mismatched Catch Types, Inappropriate Fail-Open Fallback | Flake8-Bugbear (B110, B113), CWE-775, CWE-1188, PEP-8 Style Guide |
| **`TEST_ADEQUACY`** | Untested Feature Branches, Missing Zero/Negative Boundary Coverage, Untested Core Retry Algorithm Regressions | Mutation Testing Reports, Codecov Branch Coverage Reports, Diff Change Impact Analysis |

---

## 2. Ground-Truth Specification Schema

Every evaluation case file adheres to the `EvaluationCase` schema (`evaluation/models/case.py`):

```json
{
  "case_id": "SYNTH-SEC-001",
  "category": "SECURITY",
  "title": "SQL Injection in User Search Query",
  "description": "Contextual description of the PR change",
  "affected_file": "app/services/user_search.py",
  "vulnerable_code": "... source code snippet ...",
  "fixed_code": "... reference fixed code ...",
  "ground_truth": [
    {
      "defect_id": "DEFECT-SEC-001",
      "category": "SECURITY",
      "affected_file": "app/services/user_search.py",
      "line_start": 6,
      "line_end": 7,
      "expected_issue_type": "SQL_INJECTION",
      "expected_severity": "HIGH",
      "description": "SQL Injection vulnerability via direct f-string string formatting",
      "explanation": "Constructing SQL queries by concatenating raw user parameters enables arbitrary SQL execution",
      "expected_evidence": [
        {
          "tool_name": "bandit",
          "rule_or_cve_id": "bandit.B608",
          "target_pattern": "cursor.execute(query)"
        }
      ]
    }
  ],
  "provenance": {
    "source": "synthetic_corpus",
    "author_or_curator": "evaluation_suite",
    "created_at": "2026-10-03T12:00:00Z",
    "license": "MIT",
    "ground_truth_authority": "bandit_ruleset_and_cwe",
    "annotation_uncertainty": "LOW"
  }
}
```

---

## 3. Real-World OSS Case Protocol

Human PR review comments are frequently opinionated, inconsistent, or factually incomplete. Therefore, real-world cases are curated using the following inclusion standards:

1. **Dual Verification Requirement:** A real-world defect is admitted into ground truth only if:
   - A subsequent commit/PR was merged by project maintainers to fix the issue, OR
   - An official CVE identifier or security advisory was published confirming the defect.
2. **Annotation Uncertainty Grading:**
   - `LOW`: Defect explicitly documented in official CVE advisory or maintainer release notes with test regression.
   - `MEDIUM`: Defect acknowledged in PR discussion and closed by a dedicated bugfix PR.
   - `HIGH`: Defect reported by community reviewer but closed without an explicit maintainer rationale. (Cases with HIGH uncertainty are excluded from primary benchmarks).

---

## 4. Evaluation Leakage Prevention Rules

To prevent artificial inflation of benchmark scores:
1. **No Out-of-Band Answer Leaks:** Neither defect descriptions, expected severity levels, nor expected evidence rules may be passed into model prompt inputs.
2. **Context Masking:** In real-world cases, commit messages explicitly mentioning `"Fix CVE-..."` or `"Fix bug in line 42"` are redacted from the simulated PR context.
3. **Separate Storage:** Ground-truth files are maintained in `evaluation/datasets/` and are only accessed by `evaluation/runner.py` post-inference during matching.
