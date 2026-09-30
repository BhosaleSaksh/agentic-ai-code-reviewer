# Static Analysis Architecture & Security Specification

This document details the architecture, execution engine, container security model, evidence normalization, and persistence contracts for static analysis in the Agentic AI Code Reviewer.

## 1. Overview & Scope (Phase 2.1 & Phase 2.2)

The static analysis pipeline implements isolated, containerized execution and canonical evidence normalization for:
- **Semgrep**: Polyglot static analyzer enforcing security and quality rules.
- **Bandit**: Python AST-based security vulnerability scanner.
- **pip-audit**: Dependency vulnerability scanner checking manifests against known advisory databases (PyPA / OSV).

Static analysis treats the target repository purely as **untrusted data**. Target repository code is never executed on the host or inside privileged environments. Findings are extracted strictly as structured JSON output, mapped into canonical `EvidenceModel` items, and persisted transactionally.

---

## 2. Container Images & Version Pinning

To guarantee deterministic, reproducible evaluations, all container images are pinned to specific version tags. `latest` tags are strictly prohibited.

| Analyzer | Pinned Image | Engine Version | Base / Source | Purpose |
|---|---|---|---|---|
| **Semgrep** | `semgrep/semgrep:1.78.0` | `1.78.0` | Official Semgrep Docker Hub | Multi-language semantic rules |
| **Bandit** | `ghcr.io/pycqa/bandit/bandit:1.9.4` | `1.9.4` | Official PyCQA GitHub Container Registry | Python AST security linter |
| **pip-audit** | `pip-audit:2.7.3` | `2.7.3` | `docker/pip-audit/Dockerfile` (built on `python:3.12-slim`) | Python dependency vulnerability scanner |

---

## 3. Container Execution Abstraction

The container execution abstraction is factored into a reusable pipeline:

```
                  WorkspaceContext (Phase 1.9)
                               │
                     StaticAnalysisService
                               │
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                  ▼
      SemgrepRunner      BanditRunner      PipAuditRunner
            │                  │                  │
            └──────────────────┼──────────────────┘
                               │
                   ContainerExecutionService
                               │
                     docker run (subprocess)
                               │
                        Tool Results
                               │
                    EvidenceNormalizer
                               │
                    Canonical EvidenceModels
                               │
                  EvidencePersistenceService
                               │
                      PostgreSQL DB
```

`ContainerExecutionService` manages:
- Docker command construction with strict security flags.
- Safe path translation and volume binding.
- Non-blocking asynchronous I/O stream reading.
- Configurable resource limits (memory, CPU).
- Output byte limiting to prevent memory exhaustion from oversized analyzer output.
- Execution timeouts with aggressive fallback cleanup (`docker rm -f`).
- Ephemeral execution using unique container names (`--rm`).

---

## 4. Container Security Model

The repository being analyzed is untrusted and potentially hostile. The container execution layer enforces the following controls:

1. **Non-Root Execution (`--user 1000:1000`)**:
   - The container process runs under an unprivileged UID/GID (1000:1000).
   - Root capabilities within the container namespace are forbidden.
2. **Read-Only Workspace Mount (`:ro`)**:
   - The repository workspace is mounted exclusively as read-only (`-v <workspace>:<container_path>:ro`).
   - Any attempt by an analyzer or malicious code to modify, write, or delete repository files fails with `Read-only file system` (EACCES/EROFS).
3. **Privilege Restriction (`--security-opt no-new-privileges`)**:
   - Prevents processes from gaining additional privileges via `setuid` or `setgid` binaries.
4. **No Docker Socket**:
   - The host `/var/run/docker.sock` is never mounted into the container.
5. **No Host Credential Mounts**:
   - No `.env` files, SSH keys (`~/.ssh`), cloud credentials (`~/.aws`, `~/.gcp`), or application tokens are mounted or passed in environment variables.
6. **Network Isolation (`--network none`)**:
   - Containers run with network interfaces disabled, preventing data exfiltration, command-and-control beaconing, or unauthorized external rule downloads.
   - Semgrep runs with `--metrics=off`, `--disable-version-check`, and pre-packaged local rules (`/rules/semgrep_default.yml`).
   - pip-audit operates with preloaded advisory cache (`--cache-dir /cache`) or internal OSV mirror when offline.

---

## 5. Dependency Source Strategy (pip-audit)

`PipAuditRunner` detects supported dependency manifest files in the repository:
1. `requirements.txt`
2. `requirements/*.txt` and `requirements-*.txt`
3. `pyproject.toml`
4. `Pipfile`
5. `setup.py`

### Manifest Discovery & Handling
- If requirements files are found, pip-audit audits them explicitly (`-r /workspace/<file>`).
- If only `pyproject.toml` is present, pip-audit audits the workspace project directory (`/workspace`).
- If no dependency manifest is found in the repository, `PipAuditRunner` immediately returns `StaticAnalysisExecutionStatus.NOT_APPLICABLE` without launching a container, preventing container overhead.

---

## 6. Exit-Code Semantics

Static analysis tools use non-zero exit codes to signify findings as well as execution errors. The runner decouples tool exit codes from operational failures:

### Semgrep Exit Codes
- **0**: Clean execution, findings (if any) are present in the JSON payload.
- **1**: Findings detected (when `--error` is used) or general CLI usage error.
- **2**: Fatal crash, syntax error in rules, or internal error.
- **Interpretation**: If JSON parsing succeeds and `results` is present, status is `SUCCESS_WITH_FINDINGS` (if `results` is non-empty) or `SUCCESS_NO_FINDINGS` (if `results` is empty).

### Bandit Exit Codes
- **0**: No issues detected (`SUCCESS_NO_FINDINGS`).
- **1**: Issues detected (`results` list contains one or more findings) $\rightarrow$ `SUCCESS_WITH_FINDINGS`.
- **2**: Fatal error (e.g., bad arguments, unparseable syntax) $\rightarrow$ `EXECUTION_ERROR`.

### pip-audit Exit Codes
- **0**: No known vulnerabilities detected (`SUCCESS_NO_FINDINGS`).
- **1**: Vulnerabilities detected or fatal execution error. If stdout contains valid JSON dependencies with vulnerability findings, status is `SUCCESS_WITH_FINDINGS`. If JSON is missing or invalid, status is `EXECUTION_ERROR`.
- **2**: CLI argument or configuration error $\rightarrow$ `EXECUTION_ERROR`.

---

## 7. Evidence Normalization Architecture

The normalization layer (`backend/app/static_analysis/evidence_normalizer.py`) converts tool-specific results into canonical `EvidenceModel` records without modifying the underlying analyzer contracts:

- **SemgrepResult $\rightarrow$ `EvidenceType.STATIC_ANALYSIS`**:
  - `file_path`: Normalized relative path.
  - `start_line` / `end_line`: 1-indexed source line span.
  - `snippet`: Rule explanation or message.
  - `rule_or_cve_id`: Semgrep rule ID.
  - `corroborating_tool`: `"semgrep"`.
- **BanditResult $\rightarrow$ `EvidenceType.STATIC_ANALYSIS`**:
  - `file_path`: Normalized relative path.
  - `start_line` / `end_line`: Derived from line range or single line number.
  - `snippet`: Source code excerpt or issue text.
  - `rule_or_cve_id`: `bandit.<test_id>`.
  - `corroborating_tool`: `"bandit"`.
- **PipAuditResult $\rightarrow$ `EvidenceType.DEPENDENCY`**:
  - `file_path`: Dependency declaration file (`requirements.txt`).
  - `start_line` / `end_line`: 1-indexed line where package is declared (via `find_dependency_line`).
  - `snippet`: Formatted advisory summary (`Vulnerable dependency: <package>==<version> (<vuln_id>): <desc>`).
  - `rule_or_cve_id`: Primary CVE ID (from aliases) or vulnerability identifier.
  - `corroborating_tool`: `"pip-audit"`.

### Complete Provenance Guarantee
Every `EvidenceModel.metadata` dictionary contains full provenance context:
- `analyzer`: Tool name.
- `analyzer_version`: Pinned tool version.
- `commit_sha`: Exact workspace commit SHA analyzed.
- Specific tool metadata (e.g. CWE, OWASP, severity ratings, fix versions, aliases).

---

## 8. Evidence Persistence & Idempotency

Persistence is managed by `EvidencePersistenceService` (`backend/app/services/evidence_persistence_service.py`):
- **Transactional Safety**: Persists batches inside the active database session transaction; rolls back on failure with structured `EvidencePersistenceError`.
- **Commit Guard**: Verifies that `ReviewRun.commit_sha == expected_commit_sha`. Raises `CommitMismatchError` if a mismatch is detected, preventing cross-commit evidence contamination.
- **Idempotency**: Before inserting new evidence for a tool, removes existing unlinked evidence for that tool on the target `ReviewRun`. Re-running analysis never creates duplicate rows.
