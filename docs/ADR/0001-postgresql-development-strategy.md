# 0001. PostgreSQL Development Strategy & Host vs Container Selection

## Status
Accepted

## Context
During the Phase 0.1 environment audit, the host operating system (Windows 11 x64) was discovered to have an active native installation of PostgreSQL Server 18.6 (`postgresql-x64-18`) running and listening on default port `5432`.

The authoritative project documents ([PROJECT_SPEC.md](../PROJECT_SPEC.md) Section 8 and [ARCHITECTURE.md](../ARCHITECTURE.md) Section E) state the following requirements:
- **PostgreSQL Version:** 16+ (leveraging relational integrity, JSONB indexing, and async connection pooling via `asyncpg`).
- **Roadmap Milestone:** Phase 1 specifies a `docker-compose.yml` defining database and Redis services.

Because the host machine already runs an active native PostgreSQL 18 instance on port 5432, introducing a containerized PostgreSQL instance required resolving potential port bind collisions, maintaining environment parity between local development and CI pipelines, and ensuring reproducibility across different developer machines.

---

## Decision
We **Accept Alternative B**: Use containerized PostgreSQL 16 (`postgres:16-alpine`) for the project development environment.

To prevent collision with the host machine's running PostgreSQL 18.6 service on port 5432:
- **Host Port:** `5433`
- **Container Port:** `5432`
- **Port Mapping:** `5433:5432`
- **Native Service:** The existing host Windows service (`postgresql-x64-18`) remains running on port `5432` without modification or interruption.

### Rationale
1. **Spec Alignment:** PostgreSQL 16 directly satisfies the project specification constraint (`PostgreSQL 16+`) and matches the primary baseline referenced throughout the architecture and roadmap.
2. **Reproducibility & Parity:** Running inside Docker ensures identical database behavior, extensions, and configuration across developer workstations and CI runners (e.g., GitHub Actions).
3. **Collision Avoidance:** Remapping the host port to `5433` cleanly isolates project traffic without requiring developers to stop, reconfigure, or uninstall host-level database services.
4. **Clean Lifecycle Management:** Ephemeral database instances can be reset or rebuilt using Docker volumes without impacting personal or system databases on the host.

---

## Alternatives Considered

### Alternative A: Use Host Native PostgreSQL 18.6
Connect local development directly to the existing Windows host PostgreSQL 18.6 service on `localhost:5432`.
- *Rejected Reason:* Poor reproducibility across different developer machines, configuration divergence with Linux-based CI environments, and manual database/role setup required on host.

### Alternative B: Use Containerized PostgreSQL 16 via Docker (Selected)
Run `postgres:16-alpine` inside Docker with host port mapping `5433:5432`.
- *Accepted:* Provides highest reproducibility, exact spec match, and zero interference with host services.

### Alternative C: Use Containerized PostgreSQL 18 via Docker
Run PostgreSQL 18 in a container with port mapping `5433:5432`.
- *Rejected Reason:* While modern, version 18 exceeds the baseline specified across the project documentation and may encounter compatibility gaps in certain managed cloud deployment environments.

---

## Consequences & Implementation Details

### Port Configuration
- In local development (`.env`), database connection parameters must specify port `5433`:
  ```bash
  POSTGRES_PORT=5433
  DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/agentic_reviewer
  ```
- In containerized environments and CI/CD pipelines, standard port `5432` or environment-variable injection is used.

### Migration & Deployment Implications
- **Alembic Migrations:** Alembic connects via the asynchronous SQLAlchemy engine driven by `DATABASE_URL`. Because the port is fully parameterized, migrations execute identically against `localhost:5433` locally and `postgres:5432` in Docker networking or cloud environments.
- **Service Creation Timing:** `docker-compose.yml` and container execution are deferred to Phase 1 in strict accordance with the project roadmap. No containers are created or started in Phase 0.

## Architectural Compliance
This decision complies with:
- [PROJECT_SPEC.md](../PROJECT_SPEC.md) Section 8 (Python 3.11+, PostgreSQL 16+, Redis 7+).
- [ARCHITECTURE.md](../ARCHITECTURE.md) Section E (Database Architecture: JSONB fields, async SQLAlchemy, Alembic migrations).
- [ROADMAP.md](../ROADMAP.md) Phase 1 (Foundation, Ingestion & Core Infrastructure).
