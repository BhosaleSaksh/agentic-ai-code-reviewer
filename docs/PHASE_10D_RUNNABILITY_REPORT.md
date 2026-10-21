# Phase 10D: Full-Stack Runnability and Verification Report

**Project:** An Agentic AI Framework for Reliable and Evidence-Based Automated Code Review  
**Repository:** `D:\Projects\agentic-code-reviewer`  
**Branch:** `feat/phase-7-evaluation`  
**Evaluation Mode:** Local LLM Inference (`qwen3:4b-instruct` via Ollama)  
**Safety Gate:** `GITHUB_PUBLISH_REVIEWS=false` (Strictly enforced)  
**Date:** October 21, 2026  

---

## 1. Executive Summary

This report documents the end-to-end runnability verification of the complete full-stack code review system across the FastAPI backend, Vite/React 18 frontend, Ollama local inference provider, LangGraph review orchestration DAG, and publication-safety guardrails.

All core application services and components were verified live on host ports:
- **Backend API:** FastAPI running at `http://127.0.0.1:8000` with passing `/health` and `/api/v1/health` checks.
- **Frontend SPA:** Vite/React 18 running at `http://127.0.0.1:5173` with successful HTML/JS delivery, 23/23 passing component unit tests, clean TypeScript compilation (`0` type errors), successful production bundle generation, and verified reverse-proxy connectivity to `/api/v1`.
- **Local LLM Engine:** Ollama running on `http://127.0.0.1:11434` with model storage on `D:\AI\Ollama\models` serving `qwen3:4b-instruct`.
- **Workflow & Safety Verification:** LangGraph end-to-end review graph executed successfully, detecting and verifying real findings with critic corroboration while strictly maintaining `GITHUB_PUBLISH_REVIEWS=false`.
- **Focused Test Suite:** 55 passed in 334.24s (including live Ollama specialist agent execution in the review graph).

---

## 2. Environment and Tool Versions

| Component | Path / Command | Verified Version / Status |
| :--- | :--- | :--- |
| **Operating System** | Windows 10/11 x64 (PowerShell) | Native host execution |
| **Python** | `D:\Projects\agentic-code-reviewer\.venv\Scripts\python.exe` | Python 3.12.3 |
| **Node.js** | `C:\Program Files\nodejs\node.exe` | v20.12.2 |
| **npm** | `C:\Program Files\nodejs\npm.cmd` | 10.5.0 |
| **Vite** | `frontend/node_modules/.bin/vite` | Vite v5.4.14 |
| **React** | `frontend/package.json` | React v18.3.1 |
| **FastAPI** | Backend virtual environment | FastAPI 0.110.0 / Uvicorn 0.28.0 |
| **Ollama** | `D:\Apps\Ollama\ollama.exe` | Ollama v0.40.4 |
| **Local Model** | `D:\AI\Ollama\models` | `qwen3:4b-instruct` (manifest verified) |
| **Git** | `git --version` | git version 2.44.0.windows.1 |

---

## 3. Storage and Capacity Audit

Disk space was measured using PowerShell `Get-CimInstance Win32_LogicalDisk`:

| Drive | Total Size | Free Space | Free % | Status & Safety Constraint |
| :--- | :--- | :--- | :--- | :--- |
| **C:** | 237.12 GB | **0.82 GB** | **0.35%** | **CRITICAL CONSTRAINT.** No Docker Desktop container startup, package installations, or temporary blob downloads may touch C:. |
| **D:** | 931.51 GB | **307.92 GB** | **33.05%** | **HEALTHY.** Project root, virtual environments, node_modules, and model storage all operate safely on D:. |

---

## 4. Service Architecture and Startup Order

The project architecture uses a multi-tier structure designed for resilience against external infrastructure dependencies:

```
                  +-----------------------------------+
                  |  Vite + React 18 SPA (Port 5173)  |
                  +-----------------+-----------------+
                                    | Proxies /api/v1
                                    v
                  +-----------------------------------+
                  |  FastAPI Backend App (Port 8000)  |
                  +--------+------------------+-------+
                           |                  |
             Local LLM API |                  | Direct Graph
                           v                  v
+-------------------------------+   +------------------------------------+
| Ollama Service (Port 11434)   |   | LangGraph Review Graph DAG         |
| Model: qwen3:4b-instruct      |   | - Context Bounding & Diff Parser   |
| Models Dir: D:\AI\Ollama\models|   | - Planner Agent                    |
+-------------------------------+   | - Domain Specialists Fan-Out       |
                                    | - Critic Verification & Grounding  |
                                    +------------------------------------+
```

### Verified Startup Sequence

1. **Tier 1 — Local Model Provider:**
   - Launch Ollama server with explicit model directory redirection to D::
     `$env:OLLAMA_MODELS = "D:\AI\Ollama\models"; & "D:\Apps\Ollama\ollama.exe" serve`
   - Verified listening on `127.0.0.1:11434`.
2. **Tier 2 — FastAPI Backend Application:**
   - Start Uvicorn ASGI server from backend directory:
     `.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000`
   - Verified endpoints `/health` and `/api/v1/health`.
3. **Tier 3 — Vite Frontend Dev Server:**
   - Start frontend development server with proxy configuration:
     `npm run dev -- --host 127.0.0.1 --port 5173`
   - Verified HTTP 200 delivery and reverse proxy forwarding.

---

## 5. Service-by-Service Verification Details

### 5.1 Local LLM Provider (Ollama)
- **Status:** **OPERATIONAL (HEALTHY)**
- **Endpoint:** `http://127.0.0.1:11434/api/tags`
- **Output:**
  ```json
  {"models": [{"name": "qwen3:4b-instruct", "model": "qwen3:4b-instruct", "size": 2511252199}]}
  ```
- **Live Inference Check:** Real inference smoke test (`test_real_llm_smoke.py`) passed in 7.99 seconds with `OLLAMA_READY` response and JSON structured output validation.

### 5.2 Backend API (FastAPI)
- **Status:** **OPERATIONAL (HEALTHY)**
- **Endpoint:** `http://127.0.0.1:8000/health`
- **Response:**
  ```json
  {"status": "ok", "service": "Agentic AI Code Reviewer", "version": "0.1.0", "environment": "development"}
  ```
- **API v1 Endpoint:** `http://127.0.0.1:8000/api/v1/health` -> HTTP 200 `{"status": "healthy"}`
- **Readiness Probe:** `http://127.0.0.1:8000/health/ready` -> HTTP 503 `{"status": "degraded", "database": "unavailable", "redis": "unavailable"}`
  *(Graceful degradation verified: core review orchestration and API remain responsive even when external Docker containers are stopped).*

### 5.3 Frontend Application (Vite / React 18)
- **Status:** **OPERATIONAL (HEALTHY)**
- **Dev Server URL:** `http://127.0.0.1:5173/`
- **Component Unit Tests:** `vitest run` executed 2 test files (`App.test.tsx`, `ReviewDetail.test.tsx`) with **23 passed out of 23 tests**.
- **Type Checking:** `tsc --noEmit` completed with **0 errors**.
- **Production Build:** `npm run build` compiled 1,849 modules, outputting optimized client assets (`dist/index.html` and chunks) in 20.38 seconds.
- **Proxy Verification:** `http://127.0.0.1:5173/api/v1/health` forwarded seamlessly to port 8000 and returned HTTP 200.

### 5.4 Database, Redis, MinIO, and Worker Infrastructure
- **Docker Desktop Status:** Stopped.
- **Status Rationale:** Drive C: currently has 0.82 GB free space. Starting Docker Desktop WSL2 virtual disks (`ext4.vhdx`) would trigger immediate disk exhaustion on C:.
- **Impact Assessment:** The core architecture is modular and decoupling works as intended:
  - In-memory state graphs and mock checkpointers allow local review execution and testing without Redis or PostgreSQL.
  - The API handles degraded infrastructure gracefully via clear 503 readiness payloads without process crashes.

---

## 6. End-to-End Review Smoke Test

A non-destructive end-to-end review smoke test (`scratch/run_local_review_smoke.py`) was executed to evaluate the full agentic review pipeline on a realistic code diff:

- **Target File:** `app/auth/tokens.py`
- **Injected Defect:** Hardcoded JWT secret key (`SECRET_KEY = 'hardcoded_jwt_secret_key_12345'`)
- **Corroborating Evidence:** Static analysis evidence (`bandit.B105.hardcoded_password_string`)
- **Execution Flow:**
  1. `prepare_review_context_node`: Unified diff parser verified coordinates (`@@ -10,2 +10,4 @@`), bounding diff to 2 additions and 0 deletions.
  2. `planner_node`: Bounded PR context evaluated, scoping review to `security_agent`.
  3. `security_agent_node`: Candidate finding generated with high severity and CWE-321 attribution.
  4. `critic_verification_node`: Finding validated against diff hunk line coordinates and static analysis evidence. Decision: `VERIFIED`, calibrated confidence `0.95`.
  5. `publication_gate`: Checked `settings.GITHUB_PUBLISH_REVIEWS`. Confirmed strictly `False`. No GitHub comments published.
- **Result:** **COMPLETED** (1 verified finding output).

---

## 7. Test Scope and Metric Validation

### 7.1 Focused Test Execution Summary
Command:
```powershell
.\.venv\Scripts\python.exe -m pytest `
  backend/tests/test_diff_parser.py `
  backend/tests/test_schemas.py `
  backend/tests/test_review_graph.py `
  backend/tests/test_publication_safety_invariants.py `
  backend/tests/test_real_llm_smoke.py -v
```
**Results:**
- **Passed:** **55**
- **Failed:** **0**
- **Skipped:** **0**
- **Execution Time:** 334.24 seconds (including live Ollama specialist agent inference)

### 7.2 Frontend Test Summary
Command: `npm test`
- **Test Files:** 2 passed
- **Tests:** **23 passed** (0 failed)

### 7.3 Frontend Compilation Summary
Command: `npm run lint` (`tsc --noEmit`)
- **Errors:** **0**

---

## 8. User Guide: How to Run the Application Next Time

To run the application locally on your machine, open 3 PowerShell windows and run the commands in the order shown below.

### Terminal 1: Ollama Model Server
- **Working Directory:** Any (e.g. `D:\`)
- **Command:**
  ```powershell
  $env:OLLAMA_MODELS = "D:\AI\Ollama\models"
  & "D:\Apps\Ollama\ollama.exe" serve
  ```
- **Keep Open:** Yes. Keep this window running.
- **Verification:** Visit `http://127.0.0.1:11434/api/tags` to see `qwen3:4b-instruct`.

### Terminal 2: FastAPI Backend
- **Working Directory:** `D:\Projects\agentic-code-reviewer`
- **Command:**
  ```powershell
  cd D:\Projects\agentic-code-reviewer
  .\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
  ```
- **Keep Open:** Yes. Keep this window running.
- **Verification:** Visit `http://127.0.0.1:8000/health` (should return HTTP 200 `{"status": "ok", ...}`).

### Terminal 3: Vite Frontend
- **Working Directory:** `D:\Projects\agentic-code-reviewer\frontend`
- **Command:**
  ```powershell
  cd D:\Projects\agentic-code-reviewer\frontend
  npm run dev -- --host 127.0.0.1 --port 5173
  ```
- **Keep Open:** Yes. Keep this window running.
- **Verification:** Open your browser to `http://127.0.0.1:5173/`.

---

## 9. How to Stop Services Safely

To shut down the application:
1. In each of the 3 open PowerShell terminals, press **Ctrl + C**.
2. If any process remains in the background, you can terminate them cleanly using PowerShell:
   ```powershell
   Get-Process -Name ollama, uvicorn, node -ErrorAction SilentlyContinue | Stop-Process
   ```
3. Existing model files, benchmark results, and database files remain completely intact.

---

## 10. Git Status and Commit Candidates

- **Current Branch:** `feat/phase-7-evaluation`
- **Branch Tracking:** `origin/feat/phase-7-evaluation`
- **Ahead/Behind Count:** 3 commits ahead, 0 behind (linear fast-forward).
- **Approved Documentation Candidates for Commit:**
  1. `docs/dissertation/` (12 academic chapters and front matter)
  2. `docs/PHASE_10B_GIT_CHECKPOINT_REPORT.md`
  3. `docs/PHASE_10C_DISSERTATION_READINESS.md`
  4. `docs/PHASE_10D_RUNNABILITY_REPORT.md`
- **Preserved Local Files (Excluded from Commit):**
  - `evaluation/results/pilot_results/` (local experimental artifacts, safely preserved on disk).
  - `.env` (contains local machine configuration, never committed).
