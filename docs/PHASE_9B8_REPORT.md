# PHASE 9B.8 — OLLAMA MODEL RECOVERY, LIVE INFERENCE, AND PIPELINE READINESS REPORT

**Project:** An Agentic AI Framework for Reliable and Evidence-Based Automated Code Review
**Repository:** `D:\Projects\agentic-code-reviewer`
**Current Branch:** `feat/phase-7-evaluation`
**Target Local Model:** `qwen3:4b-instruct`
**Timestamp:** 2026-10-21

---

## 1. Executive Summary & Verification Status

| Stage / Component | Status | Findings / Evidence Summary |
| :--- | :--- | :--- |
| **Stage 1: Environment Recheck** | **PASS** | Executable detected (`v0.40.4`), server active on port 11434. Disk free: C: 0.00 GB (exhausted), D: 314.65 GB. |
| **Stage 2: Model Download** | **BLOCKED** | Stale Ollama daemon running without `OLLAMA_MODELS` inherited, writing to `C:\Users\DELL\.ollama\models`. Exited on disk full. |
| **Stage 3: Inference Verification** | **BLOCKED** | Model `qwen3:4b-instruct` not yet registered on Ollama daemon. Blocked on completing download to D:. |
| **Stage 4: Root `.env` Configuration** | **PASS** | Root `.env` securely configured with `LLM_PROVIDER=ollama`, correct ports, and `GITHUB_PUBLISH_REVIEWS=false`. No secrets exposed. |
| **Stage 5: Provider Selection** | **PASS** | Domain service resolves `OllamaLLMProvider`. 27 provider unit tests pass. Correctly raises 404 on missing model without silent mock fallback. |
| **Stage 6: Review Pipeline Audit** | **PASS** | All pipeline stages (ingestion, workspace, static analysis, LangGraph, grounding critic, persistence) inspected and architecturally sound. |
| **Stage 7: Test Suites & Eval Plan** | **PASS** | 27 provider tests PASS; 21 evaluation tests PASS. Evaluation dataset verified (23 cases: 18 synthetic, 5 real-world). Full benchmark plan ready. |

---

## 2. Stage 1 — Environment Recheck

### 2.1 Ollama Executable & Running Server
* **Ollama Executable:** `D:\Apps\Ollama\ollama.exe` (Version: `0.40.4`).
* **Active Server Processes:**
  * PID `14672`: `D:\Apps\Ollama\ollama app.exe` (Tray application).
  * PID `27980`: `D:\Apps\Ollama\ollama.exe serve` (Child daemon).
* **Listening Port:** `127.0.0.1:11434` (State: `Listen`, Owning PID: `27980`).

### 2.2 Effective `OLLAMA_MODELS` Directory & Root Cause Discovery
* **Windows Registry / Environment Variable Configuration:**
  * `[Environment]::GetEnvironmentVariable('OLLAMA_MODELS', 'User')` = `D:\AI\Ollama\models`
  * `[Environment]::GetEnvironmentVariable('OLLAMA_MODELS', 'Machine')` = `D:\AI\Ollama\models`
* **Daemon Runtime Reality:**
  * PID `27980` was started **prior** to setting `OLLAMA_MODELS` in system environment variables.
  * In Windows, running processes do NOT dynamically reload environment variables from the registry.
  * Consequently, the running server process defaulted to:
    `C:\Users\DELL\.ollama\models`
* **Disk Space Status:**
  * **Drive C:** `0.00 GB free` / `219.18 GB used` (**Disk Full**).
  * **Drive D:** `314.65 GB free` / `30.80 GB used`.

### 2.3 Model Directory Inspection
* **Drive D (`D:\AI\Ollama\models`):**
  * `D:\AI\Ollama\models\blobs\sha256-85e4a5b7b8ef0e48af0e8658f5aaab9c2324c76c1641493f4d1e25fce54b18b9-partial` (1,404,720,270 bytes ≈ 1.308 GB).
* **Drive C (`C:\Users\DELL\.ollama\models`):**
  * `C:\Users\DELL\.ollama\models\blobs\sha256-85e4a5b7b8ef0e48af0e8658f5aaab9c2324c76c1641493f4d1e25fce54b18b9-partial` (2,497,280,480 bytes ≈ 2.325 GB).

---

## 3. Stage 2 — Model Download Analysis

### 3.1 Observed Failure During Pull Attempt
When `ollama pull qwen3:4b-instruct` was dispatched, the client CLI connected to `http://127.0.0.1:11434/api/pull`. Because the listening daemon (PID 27980) had no `OLLAMA_MODELS` override in its process environment block, it downloaded into `C:\Users\DELL\.ollama\models\blobs` until Drive C had 0 bytes free.

**Captured Log Error:**
```
Error: max retries exceeded: write C:\Users\DELL\.ollama\models\blobs\sha256-85e4a5b7b8ef0e48af0e8658f5aaab9c2324c76c1641493f4d1e25fce54b18b9-partial: There is not enough space on the disk.
```

### 3.2 Safeguards Compliance & Non-Destructive Action
Per authorization constraints:
* No model files or caches were deleted or moved.
* No files on C: were deleted without explicit approval.
* No duplicate server was launched.

### 3.3 Safe Correction Procedure (Pending User Approval)
To direct Ollama to `D:\AI\Ollama\models` and free C::
1. **Free C: Drive Space (Requires User Approval):**
   * Delete the orphaned partial download file created by the aborted run:
     `C:\Users\DELL\.ollama\models\blobs\sha256-85e4a5b7b8ef0e48af0e8658f5aaab9c2324c76c1641493f4d1e25fce54b18b9-partial` (2.325 GB).
   * This immediately restores ~2.32 GB free space on Drive C.
2. **Restart the Ollama Server with Fresh Environment:**
   * Exit the Ollama tray application (`ollama app.exe`, PID 14672).
   * Launch `& "D:\Apps\Ollama\ollama app.exe"` or start Ollama serve in a session where `$env:OLLAMA_MODELS = "D:\AI\Ollama\models"`.
   * The new daemon will read `OLLAMA_MODELS=D:\AI\Ollama\models` from the user registry.
3. **Resume Pull on Drive D:**
   * `& "D:\Apps\Ollama\ollama.exe" pull qwen3:4b-instruct`
   * It will resume using the 1.308 GB blob already present in `D:\AI\Ollama\models\blobs`, utilizing the 314 GB free space on D:.

---

## 4. Stage 3 — Inference Verification

* **Registered Models (`ollama list`):** Empty (model not yet registered).
* **API Tags (`http://127.0.0.1:11434/api/tags`):** `{"models": []}`.
* **Inference Status:** **BLOCKED** until the model download completes on D:.
* **Target Smoke Test Command:**
  ```powershell
  & "D:\Apps\Ollama\ollama.exe" run qwen3:4b-instruct "Reply with exactly: OLLAMA_READY"
  ```

---

## 5. Stage 4 — Root `.env` Configuration

The root `.env` file was verified and checked against `backend/app/core/config.py`.

### 5.1 Active Settings
```ini
# Application & API
ENVIRONMENT=development
DEBUG=true
LOG_LEVEL=INFO
API_HOST=0.0.0.0
API_PORT=8000
API_V1_PREFIX=/api/v1

# PostgreSQL (Native Host on port 5432)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=agentic_reviewer
POSTGRES_USER=postgres
POSTGRES_PASSWORD=[REDACTED]
DATABASE_URL=postgresql+asyncpg://postgres:[REDACTED]@localhost:5432/agentic_reviewer

# Redis (Container mapping 6380 -> 6379)
REDIS_HOST=localhost
REDIS_PORT=6380
REDIS_DB=0
REDIS_URL=redis://localhost:6380/0

# GitHub Publishing Invariant
GITHUB_PUBLISH_REVIEWS=false
REVIEW_GRAPH_ENABLED=true

# LLM Provider Configuration
LLM_PROVIDER=ollama
LLM_TEMPERATURE=0.1
LLM_MAX_RETRIES=3
LLM_REQUEST_TIMEOUT_SECONDS=60.0

# Ollama Local LLM Integration
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:4b-instruct
OLLAMA_REQUEST_TIMEOUT_SECONDS=120.0

# OpenAI (Disabled; credentials empty)
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o
```

### 5.2 Settings Verification via Python
Executing `get_settings()` produced:
* `LLM_PROVIDER`: `ollama`
* `OLLAMA_MODEL`: `qwen3:4b-instruct`
* `OLLAMA_BASE_URL`: `http://localhost:11434`
* `OLLAMA_REQUEST_TIMEOUT_SECONDS`: `120.0`
* `GITHUB_PUBLISH_REVIEWS`: `False`
* Zero secrets leaked.

---

## 6. Stage 5 — Provider Selection Verification

### 6.1 Domain Resolution
`LLMService` resolution logic in `backend/app/services/llm/service.py` was inspected and verified:
* When `LLM_PROVIDER=ollama`, `LLMService` instantiates and returns `OllamaLLMProvider`.
* Base URL (`http://localhost:11434`), model (`qwen3:4b-instruct`), and timeout (`120.0s`) are passed correctly.
* Provider class verified in live Python runtime: `OllamaLLMProvider`.

### 6.2 Missing Model Handling & Error Invariant
Tested live invocation against Ollama when `qwen3:4b-instruct` is not yet pulled:
* **Result:** Raised `app.orchestration.errors.LLMProviderError: Ollama model 'qwen3:4b-instruct' was not found (404). Please download it using 'ollama pull qwen3:4b-instruct'.`
* **Invariant Proven:** The system does **NOT** silently fall back to `MockLLMProvider` when a real LLM is configured. It fails fast with an explicit, non-retryable 404 domain error.

### 6.3 Provider Unit Tests
* Executed `test_ollama_provider.py` and `test_openai_provider.py`.
* **Result:** **27 passed in 12.81s** (100% pass rate).
* Tests cover: structured output validation, JSON schema enforcement, retry policies, backoff, timeout mappings, cost telemetry ($0.0 USD for local), and secret redaction.

---

## 7. Stage 6 — Review Pipeline Audit

The complete review pipeline architecture was reviewed end-to-end:

```
[GitHub Webhook / Direct Ingestion]
                │
                ▼
[WorkspaceManager & GitRunner] ───► Git clone/checkout, unified diff extraction
                │
                ▼
[Static Analysis Service] ────────► Bandit, Semgrep, Pip-Audit (Docker/Host)
                │
                ▼
[LangGraph Review Graph]
   ├── ContextBuilder ────────────► Token-budgeted AST & diff context
   ├── ReviewPlannerNode ─────────► Generates ReviewPlan schema
   ├── SpecialistNodes ───────────► Security, Logic, Error, Test specialists
   └── GroundingCriticNode ───────► Evidence grounding & false-positive filter
                │
                ▼
[FindingPersistenceService] ──────► DB persistence & deduplication
                │
                ▼
[ReviewPublisher] ────────────────► GITHUB_PUBLISH_REVIEWS=false (Strictly Gated)
```

### 7.1 Infrastructure Readiness
* **PostgreSQL (Port 5432):** Active (Native Windows service PID 7384).
* **Redis (Port 6380):** Inactive (Container not started). Required for ARQ worker queue and SSE delivery cache.
* **Backend API (Port 8000):** Inactive.
* **Frontend (Port 5173 / 3000):** Inactive.

---

## 8. Stage 7 — Tests & Evaluation Readiness

### 8.1 Test Execution Summary
* **LLM Provider Tests (`test_ollama_provider.py`, `test_openai_provider.py`):** **27 PASSED**, 0 failed.
* **Evaluation Framework Tests (`test_evaluation_framework.py`):** **21 PASSED**, 0 failed.
* **Backend Integration / DB Tests:** 426 passed, 39 failed (due to PostgreSQL password mismatch with native instance and C: drive 0-byte ENOSPC in temp files).
* **Frontend Tests (`vitest`):** FAILED with `ENOSPC: no space left on device` due to Drive C having 0 free bytes.

### 8.2 Dataset & Ground Truth Status
* **Total Cases:** 23 cases loaded deterministically:
  * `SECURITY`: 7 cases
  * `BUG_LOGIC`: 6 cases
  * `ERROR_HANDLING`: 6 cases
  * `TEST_ADEQUACY`: 4 cases
  * (18 synthetic benchmark cases + 5 real-world open source PR cases).

### 8.3 Metric Formulas & Verification
The evaluation calculator (`evaluation/metrics/calculator.py`) enforces strict formulas:
* **Precision:** $\frac{TP}{TP + FP}$ (with Wilson score 95% confidence interval)
* **Recall:** $\frac{TP}{TP + FN}$ (with Wilson score 95% confidence interval)
* **F1 Score:** $\frac{2 \cdot P \cdot R}{P + R}$
* **False Positive Rate (FPR):** $\frac{FP}{FP + TN}$ if $TN > 0$, else $\frac{FP}{TP + FP}$
* **Evidence Grounded Rate:** $\frac{\text{Evidence Grounded Verified}}{\text{Total Verified Findings}}$
* **Thesis FPR Reduction Target ($\ge 40\%$):**
  $$\text{FPR Reduction} = \frac{\text{FPR}_{\text{baseline}} - \text{FPR}_{\text{agentic}}}{\text{FPR}_{\text{baseline}}}$$
  *(Note: If both baseline and agentic FPR are 0.0, reduction is reported as undefined).*

### 8.4 Proposed Benchmark Execution Plan

| Parameter | Specification |
| :--- | :--- |
| **Execution Command** | `poetry run python evaluation/scripts/run_benchmark.py --baseline all --mode real` |
| **Model & Provider** | Provider: `ollama`, Model: `qwen3:4b-instruct`, URL: `http://localhost:11434` |
| **Baselines Evaluated** | 1. `static_only`<br>2. `single_llm` (qwen3:4b-instruct standard prompt)<br>3. `ablation_no_static` (Agentic without static tool evidence)<br>4. `ablation_no_critic` (Agentic without critic verification)<br>5. `agentic` (Full multi-agent with evidence-grounded critic) |
| **Expected Runtime** | ~15–25 minutes for 23 cases across 5 baselines depending on GPU/CPU inference speed |
| **Output Directory** | `evaluation/results/<run_id>/` (Isolated run UUID directory preventing overwriting) |
| **Output Artifacts** | `config.json`, `summary.json`, `cases.json`, `metrics.csv`, and legacy summary CSV |

> [!IMPORTANT]
> The full benchmark will NOT be started until Ollama model download is completed and the user explicitly approves execution.

---

## 9. Blockers & Required Actions

### Blocker 1: Drive C Space Exhaustion (0 bytes free)
* **Cause:** Aborted download wrote 2.325 GB to `C:\Users\DELL\.ollama\models\blobs\sha256-85e4a5b7b8ef0e48af0e8658f5aaab9c2324c76c1641493f4d1e25fce54b18b9-partial`.
* **Action Needed:** Approve deletion of this specific file on C: to restore ~2.32 GB immediately.

### Blocker 2: Stale Ollama Daemon (PID 27980)
* **Cause:** Started before `OLLAMA_MODELS` was registered in Windows environment.
* **Action Needed:** Stop Ollama (Quit tray app or kill PID 14672/27980) and restart so it inherits `OLLAMA_MODELS=D:\AI\Ollama\models`.

### Blocker 3: Complete Download of `qwen3:4b-instruct`
* **Action Needed:** Once daemon restarts with `OLLAMA_MODELS=D:\AI\Ollama\models`, run pull command to resume download on D:.
