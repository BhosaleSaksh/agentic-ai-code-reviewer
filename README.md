# An Agentic AI Framework for Reliable and Evidence-Based Automated Code Review

## Project Purpose
This project designs and implements an enterprise-grade, multi-agent AI framework for automated Pull Request code review on GitHub. Moving beyond single-prompt LLM reviewers that suffer from hallucinations, high false positive rates, and subjective feedback, this framework orchestrates specialized analysis agents (Security, Bug & Logic, Error Handling, Test Adequacy) within a stateful LangGraph Directed Acyclic Graph (DAG). Findings are corroborated by deterministic static analysis tools (Semgrep, Bandit, pip-audit) in isolated sandboxes and strictly validated by an adversarial Critic/Verification Agent prior to GitHub review publication.

## Current Development Status
- **Current Milestone:** Phase 0 — Checkpoint 0.2: Repository Foundation & Environment Configuration.
- **Implementation State:** The repository is currently in the foundation phase. Core specifications, engineering architecture, and environment configuration have been established. Application business logic, database migrations, and agent workflows are scheduled in upcoming roadmap phases.

## Authoritative Project Documents
All engineering implementation must adhere strictly to the authoritative project specifications:
- [PROJECT_SPEC.md](docs/PROJECT_SPEC.md): Functional/non-functional requirements, acceptance criteria, and measurable evaluation KPIs.
- [ARCHITECTURE.md](docs/ARCHITECTURE.md): System architecture, 8-layer design, data flow, component rules, and schemas.
- [ROADMAP.md](docs/ROADMAP.md): Phased engineering roadmap, dependencies, milestones, and verifiable delivery criteria.

## High-Level Technology Stack
- **Backend Runtime:** Python 3.11+ / FastAPI (asynchronous ASGI framework)
- **Agent Orchestration:** LangGraph state machine & multi-agent runtime
- **Database & Persistence:** PostgreSQL 16+ (relational integrity, JSONB records)
- **Asynchronous Task Queue:** Redis 7+ & ARQ worker
- **Static Analysis Tools:** Semgrep, Bandit, pip-audit (executed in isolated Docker sandboxes)
- **Frontend Dashboard:** React 18+, TypeScript 5+, Vite
- **Version Control & Ingress:** GitHub Webhooks (HMAC-SHA256 verified) & GitHub REST API

## Development Philosophy
1. **Evidence-Based Grounding:** Every critique must be tethered to concrete diff coordinates, AST context, or static analysis rule matches.
2. **Zero Hallucination Ingress:** Speculative or unverified commentary is rejected; comments are published only if validated against active diff lines with confidence $\ge 0.75$.
3. **Modularity & Clean Architecture:** Strict separation of concerns with zero business logic in API route handlers and isolated service abstractions.
4. **Adversarial Verification:** Critic-in-the-loop validation to actively suppress false positives and minimize developer alert fatigue.
