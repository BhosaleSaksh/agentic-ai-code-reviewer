# Architecture Decision Records (ADR)

## Overview
This directory contains the Architecture Decision Records (ADRs) for the **Agentic AI Code Reviewer** project.

An Architecture Decision Record captures significant architectural, technical, or design decisions made during the evolution of the system, along with their context, rationale, alternatives considered, and consequences.

## Numbering & Naming Convention
ADRs are stored as sequential markdown documents following the pattern:
```
docs/ADR/NNNN-short-descriptive-title.md
```
Example:
- `docs/ADR/0001-record-architecture-decisions.md`
- `docs/ADR/0002-use-langgraph-for-agent-orchestration.md`

## ADR Structure & Template
Every ADR should follow this standardized template:

```markdown
# [NNNN]. [Short Title of Decision]

## Status
[Proposed | Accepted | Superseded | Deprecated] (If superseded, link to successor ADR)

## Context
What problem or context prompted this decision? What constraints or requirements influenced the choice?

## Decision
What is the change or architecture design that we are committing to? What technologies or design patterns are adopted?

## Consequences
### Positive
- What benefits or architectural advantages does this decision bring?

### Negative / Trade-offs
- What complexities, limitations, or additional operational burdens are introduced?

## Compliance & Architectural Alignment
How does this decision adhere to [ARCHITECTURE.md](../ARCHITECTURE.md) and [PROJECT_SPEC.md](../PROJECT_SPEC.md)?
```

## Lifecycle of an ADR
1. **Proposed:** The ADR is written and undergoing review.
2. **Accepted:** The decision has been approved and forms part of the project's authoritative architectural baseline.
3. **Superseded:** A later decision replaces or significantly modifies this ADR (referenced via link).
4. **Deprecated:** The decision is no longer applicable.
