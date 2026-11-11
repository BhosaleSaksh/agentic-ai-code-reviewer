# System Runbook & Presentation Guide

**Project:** An Agentic AI Framework for Reliable and Evidence-Based Automated Code Review  
**Repository:** `D:\Projects\agentic-code-reviewer`  
**Purpose:** Comprehensive guide detailing exact startup commands, database operations, health checks, demo presentation walkthrough, and shutdown procedures.

---

## 1. System Architecture & Port Mapping

| Component | Host Port | Working Directory / Binary | Description |
| :--- | :--- | :--- | :--- |
| **PostgreSQL Database** | `5433` | `C:\Program Files\PostgreSQL\18\bin\postgres.exe` | Project-isolated cluster on `D:\pgdata` (`agentic_reviewer`) |
| **Ollama Local LLM** | `11434` | `D:\Apps\Ollama\ollama.exe` | Local inference engine serving `qwen3:4b-instruct` |
| **FastAPI Backend** | `8000` | `D:\Projects\agentic-code-reviewer` | REST API, LangGraph DAG, and review pipeline |
| **Vite / React Frontend** | `5173` | `D:\Projects\agentic-code-reviewer\frontend` | Interactive observability dashboard (proxies `/api` -> `8000`) |

---

## 2. Step-by-Step Application Startup

To start the complete application locally, open **4 PowerShell terminals** and run the respective command in each:

### Terminal 1: PostgreSQL Database (Port 5433)
Start the dedicated database instance storing review telemetry and findings:
```powershell
& "C:\Program Files\PostgreSQL\18\bin\postgres.exe" -D "D:\pgdata" -p 5433
```
* **Expected Output:** `LOG: database system is ready to accept connections`
* **Keep Open:** Yes. Keep this window running.

---

### Terminal 2: Ollama Local LLM Server (Port 11434)
Start the local model engine with models loaded from Drive `D:`:
```powershell
$env:OLLAMA_MODELS = "D:\AI\Ollama\models"
& "D:\Apps\Ollama\ollama.exe" serve
```
* **Expected Output:** Ollama server listening on `127.0.0.1:11434`.
* **Quick Verification:**
  ```powershell
  curl.exe -s http://127.0.0.1:11434/api/tags
  ```
  *(Should list `qwen3:4b-instruct`).*
* **Keep Open:** Yes. Keep this window running.

---

### Terminal 3: FastAPI Backend Application (Port 8000)
Start the Python ASGI backend:
```powershell
cd D:\Projects\agentic-code-reviewer
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```
* **Expected Output:**
  ```text
  INFO:     Started server process [...]
  INFO:     Application startup complete.
  INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
  ```
* **Keep Open:** Yes. Keep this window running.

---

### Terminal 4: Vite React Frontend Dashboard (Port 5173)
Start the frontend development server:
```powershell
cd D:\Projects\agentic-code-reviewer\frontend
npm run dev -- --host 127.0.0.1 --port 5173
```
* **Expected Output:**
  ```text
  VITE ready in ... ms
  ➜  Local:   http://127.0.0.1:5173/
  ```
* **Keep Open:** Yes. Keep this window running.

---

## 3. Database Management & Data Seeding

### 3.1 Run Database Migrations
If you ever reset the database or add new tables, execute:
```powershell
cd D:\Projects\agentic-code-reviewer
.\.venv\Scripts\alembic.exe upgrade head
```

### 3.2 Seed Presentation Demonstration Data
To populate the 5 repositories, 11 pull requests, 11 review executions, 18 findings, static analysis evidence items, and developer feedback:
```powershell
cd D:\Projects\agentic-code-reviewer
.\.venv\Scripts\python.exe backend/scripts/seed_demo_data.py
```
* **Expected Output:** `Presentation dataset successfully seeded!`

---

## 4. Verification & Health Check Commands

You can run these curl commands from any PowerShell terminal to verify system status:

| Check | PowerShell Command | Expected Result |
| :--- | :--- | :--- |
| **Backend Liveness** | `curl.exe -s http://127.0.0.1:8000/health` | `{"status":"ok", ...}` |
| **Database Readiness** | `curl.exe -s http://127.0.0.1:8000/health/ready` | `"database":{"status":"healthy"}` |
| **Frontend Proxy** | `curl.exe -s http://127.0.0.1:5173/api/v1/health` | `{"status":"ok", ...}` |
| **Dashboard Metrics** | `curl.exe -s http://127.0.0.1:5173/api/v1/dashboard/metrics` | Returns totals (5 repos, 11 PRs, etc.) |
| **Swagger API Docs** | Open browser to `http://127.0.0.1:8000/docs` | Interactive OpenAPI documentation |

---

## 5. Presentation Demo Walkthrough (Step-by-Step Script)

When presenting tomorrow, open your browser to **`http://127.0.0.1:5173/dashboard`** and follow this narrative:

### Step 1: High-Level Observability Dashboard (`/dashboard`)
* **Show the Metric Cards:**
  - **Tracked Repositories (5):** Explains that the platform monitors heterogeneous enterprise microservices (Auth, Payment, Data Pipeline, Core API, Frontend).
  - **Pull Requests (11):** Ingested via GitHub Webhooks with verified HMAC-SHA256 signatures.
  - **Review Runs (11):** Highlights **1 Active / Running** review (`feat(dashboard): add real-time websocket metrics stream`) alongside completed executions.
  - **Verified vs. Rejected Findings (14 vs. 4):** Emphasizes the **Critic-in-the-Loop** mechanism that eliminates hallucination and suppresses developer alert fatigue.
* **Show the Recent Review Executions Table:**
  - Point out realistic execution durations (**4.2s to 12.1s**), token efficiency (**~1.5k–4.2k tokens**), and low per-review costs (**$0.003–$0.008**).

### Step 2: Repositories & Ingestion Architecture (`/repositories`)
* Navigate to the **Repositories** tab in the sidebar.
* Highlight multi-repository isolation and branch tracking (`enterprise-ai/payment-gateway`, `enterprise-ai/auth-service`, etc.).

### Step 3: Pull Requests (`/pull-requests`)
* Navigate to **Pull Requests**.
* Show real diff statistics (additions, deletions, changed files count) and how PRs link to review executions.

### Step 4: Review Pipeline & Multi-Agent DAG (`/reviews`)
* Navigate to **Review Runs**.
* Click **Details** on `enterprise-ai/payment-gateway` (PR #218):
  - Explain the **LangGraph DAG review plan**:
    1. **Diff Bounding & Context Preparation:** Limits token consumption strictly to modified hunk coordinates and AST context.
    2. **Specialist Fan-Out:** Explains how specialized agents (`SecurityAgent`, `BugLogicAgent`, `TestAdequacyAgent`) run in parallel.
    3. **Adversarial Critic Verification:** Validates findings against diff lines and static analysis rule matches before publishing.

### Step 5: Evidence Grounding & False Positive Suppression (`/findings`)
* Navigate to **Findings**.
* **High-Impact Verified Findings:**
  - *TOCTOU Race Condition in Idempotency Check (CWE-367)*: Corroborated by AST concurrency analyzer.
  - *Insecure Deserialization via pickle.loads (CWE-502)*: Corroborated by `bandit.B301`.
  - *Tenant Scoping IDOR (CWE-639)*: Corroborated by `semgrep.security.unvalidated-tenant-access`.
  - *Vulnerable Dependency (CVE-2024-34064)*: Corroborated by `pip-audit`.
* **Critic-Suppressed Findings (Filter/Look for REJECTED):**
  - Show how the Critic Agent actively filtered out low-confidence stylistic nitpicks and speculative micro-optimizations, explaining the rejection rationale to the audience.

### Step 6: Developer Feedback & Continuous Calibration (`/feedback`)
* Navigate to **Feedback**.
* Show recorded developer feedback events:
  - Positive reactions (`REACTION_POSITIVE`), comment resolutions, and confirmation that findings were accepted and patched.
  - Explains how this feedback loop continuously measures precision and recall.

---

## 6. How to Stop All Services Cleanly

To stop the entire application stack:
1. Press `Ctrl + C` in each of the PowerShell terminal windows.
2. Or run this single cleanup command in PowerShell to stop any lingering background processes:
```powershell
Get-Process -Name postgres, ollama, uvicorn, node -ErrorAction SilentlyContinue | Stop-Process
```
*(All seeded data and model files remain safely preserved on Drive D).*
