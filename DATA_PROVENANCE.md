# Data Provenance Audit Report

**Project:** Agentic AI Framework for Reliable and Evidence-Based Automated Code Review  
**Milestone:** Phase 7 — Evaluation, Benchmarking & Data Provenance  
**Date:** 2026-10-03  
**Audit Scope:** Repository, Pull Request, Review Run, Finding, Evidence, Feedback, Publication, and Webhook records across the database and frontend codebase.

---

## 1. Executive Summary

This audit establishes the origin and provenance of all entities currently displayed in the Phase 6 Review Dashboard and stored in PostgreSQL.

**Key Findings:**
1. **The current dashboard data is synthetic and test-generated.** It does not originate from live GitHub production webhooks connected to real open-source repositories.
2. **Frontend Cleanliness:** The React frontend contains **zero hardcoded records, mock constants, or fixture fallbacks**. All views are dynamically driven by backend REST APIs (`/api/v1/...`).
3. **Database Provenance:** The records currently present in PostgreSQL originate from two specific sources:
   - **Test Suite Residuals (63 records):** Generated and committed by `backend/tests/test_finding_mapper.py::test_database_persistence_of_mapped_finding` during automated test runs.
   - **Manual Verification Seed Hierarchy (1 record hierarchy):** A synthetic demonstration record hierarchy (`test-org/review-demo`) created during Phase 6 verification to validate full dashboard navigation and UI states.
4. **Webhook Deliveries (1,137 records):** Accumulated during unit and integration test executions of `backend/tests/test_webhooks.py` and `backend/tests/test_queue.py`.

---

## 2. Inventory of Database Records

A complete audit of PostgreSQL was performed via asynchronous SQLAlchemy reflection against the active database:

| Entity Type | Total Count | Test Suite Residuals | Seed/Demo Records | Genuine Live Production |
| :--- | :--- | :--- | :--- | :--- |
| **Repositories** | 64 | 63 (`test-owner/test-repo-*`) | 1 (`test-org/review-demo`) | 0 |
| **Pull Requests** | 64 | 63 (`Add authentication module`) | 1 (`feat: secure payment flow`) | 0 |
| **Review Runs** | 64 | 63 (`completed`) | 1 (`COMPLETED`) | 0 |
| **Findings** | 65 | 63 (`Weak Password Hashing Scheme`) | 2 (`SQL Injection`, `Minor variable naming`) | 0 |
| **Evidence Items** | 64 | 63 (`bandit.B303`) | 1 (`bandit.B608`) | 0 |
| **Review Feedback** | 1 | 0 | 1 (User: `alice`, `REACTION_POSITIVE`) | 0 |
| **Review Publications** | 1 | 0 | 1 (`PUBLISHED`, comment: `11223344`) | 0 |
| **Webhook Deliveries**| 1,137 | 1,137 (Test payload deliveries) | 0 | 0 |

---

## 3. Detailed Entity Provenance

### 3.1. Dashboard Metrics and Repository Records
- **Database Table:** `repositories`
- **Origin of Records:**
  - 63 rows: `test_finding_mapper.py` (lines 211–218). In `test_database_persistence_of_mapped_finding()`, each pytest execution instantiates `Repository(full_name=f"test-owner/test-repo-{uuid.uuid4().hex[:6]}")` and calls `session.commit()`. Because no teardown was included in this test, records accumulated across the 63 test suite runs.
  - 1 row: `test-org/review-demo` (UUID: `38f9cd2a-4cb4-456e-aeb2-109c9381fb27`). Seeded during Phase 6 dashboard verification matching the schema of `backend/tests/test_dashboard_api.py::sample_dataset`.
- **Live Runtime Webhooks:** None connected to external internet GitHub repositories.

### 3.2. Pull Request Records
- **Database Table:** `pull_requests`
- **Origin of Records:**
  - 63 rows: `test_finding_mapper.py` (lines 220–230). Each row has title `"Add authentication module"`, `author="dev"`, `base_sha="0000000000000000000000000000000000000001"`, `head_sha="0000000000000000000000000000000000000002"`.
  - 1 row: PR #42 `"feat: secure payment flow"`, `author="alice"`, 120 additions, 15 deletions, 3 changed files.

### 3.3. Review Run Records
- **Database Table:** `review_runs`
- **Origin of Records:**
  - 63 rows: `test_finding_mapper.py` (lines 232–238). Status `"completed"`, associated with the 63 test pull requests.
  - 1 row: Review Run UUID `2fb7a7cb-09e9-4f99-ba03-b302c9ce59cc`, status `"COMPLETED"`, `trigger_type="WEBHOOK"`, `total_tokens=1500`, `total_cost_usd=0.035`, `latency_seconds=12.4`, review plan containing `focus="security"` and `specialists=["security", "correctness"]`.

### 3.4. Findings & Critic Verification Status
- **Database Table:** `findings`
- **Origin of Records:**
  - 63 rows: `test_finding_mapper.py` (lines 240–275). All 63 represent the test finding `"Weak Password Hashing Scheme"` in file `backend/app/auth.py` at line 35, severity `HIGH`, verification status `VERIFIED`, publish status `PUBLISHED`.
  - 2 rows:
    1. `"SQL Injection Vulnerability"`: `src/payment.py` line 45, severity `HIGH`, verification status `VERIFIED`, publish status `PUBLISHED`.
    2. `"Minor variable naming nitpick"`: `src/utils.py` line 10, severity `LOW`, verification status `REJECTED`, rejection reason `"Low severity stylistic nitpick dropped by critic policy"`.

### 3.5. Evidence Grounding Items
- **Database Table:** `evidence_items`
- **Origin of Records:**
  - 63 rows: `test_finding_mapper.py` (lines 258–268). Evidence type `STATIC_ANALYSIS`, tool `bandit`, rule `bandit.B303`, snippet `hashlib.md5(password.encode()).hexdigest()`.
  - 1 row: Evidence attached to the SQL injection finding: rule `bandit.B608`, tool `bandit`, snippet `cursor.execute(f"SELECT * FROM accounts WHERE id = {acc_id}")`, lines 44–46 of `src/payment.py`.

### 3.6. User Feedback Records
- **Database Table:** `review_feedback`
- **Origin of Records:**
  - 1 row: `id=d3e7c65a-5e4d-4ade-99e8-71bf3981556f`, `reviewer_username="alice"`, `feedback_type="REACTION_POSITIVE"`, metadata `{"reaction_content": "+1"}`. Corresponds to the feedback webhook test fixture in Phase 5 / Phase 6.

### 3.7. Publication Audit Records
- **Database Table:** `review_publications`
- **Origin of Records:**
  - 1 row: `id=759e4d13-8069-4fd4-a672-1548d4d534a9`, associated with review run `2fb7a7cb-09e9-4f99-ba03-b302c9ce59cc`, status `PUBLISHED`, GitHub comment ID `11223344`.

### 3.8. Webhook Deliveries
- **Database Table:** `webhook_deliveries`
- **Origin of Records:**
  - 1,137 rows: Generated during automated runs of `backend/tests/test_webhooks.py` and `backend/tests/test_queue.py`. All events are test payloads (`pull_request.opened`, `pull_request.synchronize`, `ping`) processed by the ingestion endpoint.

---

## 4. Frontend Codebase Audit

A full AST and pattern search of the frontend codebase (`frontend/src/`) was conducted:

| Category | Search Pattern | Result | Notes |
| :--- | :--- | :--- | :--- |
| **Mock Arrays** | `mockRepositories`, `mockFindings`, `dummyPRs` | **None** | No static mock arrays in component files. |
| **Hardcoded CVEs** | `CVE-`, `bandit.`, `semgrep.` | **None in src/components or src/features** | Only referenced in test assertions (`src/test/app.test.tsx`). |
| **Hardcoded Repos** | `facebook/react`, `owner/repo` | **None** | All repo cards dynamically render from API response. |
| **API Client** | `fetch`, `axios`, `apiClient` | **Consistent** | All data routes go through `apiClient` to `/api/v1/...`. |

**Verdict:** The React frontend is completely clean of hardcoded production or demo data. It is a genuine consumer of backend database state.

---

## 5. Exact Files Responsible for Seeded / Test Data

1. **`backend/tests/test_finding_mapper.py`**:
   - Lines 207–275: Generates a new `Repository`, `PullRequest`, `ReviewRun`, `Finding`, and `EvidenceItem` on each test run and commits it via `get_db_session()`.
2. **`backend/tests/test_dashboard_api.py`**:
   - Lines 60–218: Defines the canonical `sample_dataset` fixture structure (`test-org/review-demo`, PR 42, SQL injection finding, critic-rejected nitpick, bandit evidence, publication audit, feedback).
3. **`backend/tests/test_webhooks.py`**:
   - Lines 120–580: Posts synthetic webhook delivery payloads to `/api/v1/webhooks/github`, inserting rows into `webhook_deliveries`.

---

## 6. Audit Conclusion & Implication for Phase 7 Evaluation

1. **Synthetic Nature of Existing Records:** The current database contents are exclusively **synthetic test fixtures and verification records**. No real open-source developer PRs or findings exist yet in the database.
2. **Evaluation Framework Requirement:** Phase 7 must establish an isolated, reproducible benchmark evaluation corpus under `evaluation/` with controlled synthetic cases and real-world PR manifests.
3. **Zero Production Contamination:** The evaluation corpus and harness will reside strictly in `evaluation/`, ensuring neither production schemas nor the real database tables are polluted with ungrounded test artifacts.
