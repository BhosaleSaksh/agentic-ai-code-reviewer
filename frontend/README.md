# Agentic AI Code Reviewer — Frontend Dashboard

This directory contains the React + TypeScript frontend dashboard for the **Agentic AI Code Reviewer** platform.

## Quick Start

### 1. Install Dependencies
```bash
npm install
```

### 2. Development Server
```bash
npm run dev
```
The Vite development server runs at `http://localhost:5173` and proxies API requests `/api/*` to the FastAPI backend at `http://localhost:8000`.

### 3. Production Build
```bash
npm run build
```

### 4. Run Tests & Linter
```bash
npm run test
npm run lint
```

## Structure
- `src/app`: Application router, providers, and environment config.
- `src/components`: UI primitives (`StatCard`, `Badge`, `StatusBadge`, `SeverityBadge`, `ErrorState`, `LoadingState`, `EmptyState`) and domain components (`FindingCard`, `EvidenceCard`, `ReviewPipeline`, `FeedbackCard`).
- `src/features`: Screen implementations (`dashboard`, `repositories`, `pull-requests`, `review-runs`, `findings`, `feedback`).
- `src/lib`: API clients, TanStack Query key factory, formatters.
- `src/types`: Strongly-typed TypeScript interfaces mapping directly to backend FastAPI schemas.
