/**
 * Systematic TanStack Query keys factory for consistent server state management.
 */

export const queryKeys = {
  dashboard: {
    metrics: ["dashboard", "metrics"] as const,
  },
  repositories: {
    all: ["repositories"] as const,
    list: (limit?: number, offset?: number) =>
      ["repositories", "list", { limit, offset }] as const,
    detail: (id: string) => ["repositories", "detail", id] as const,
    pullRequests: (id: string, state?: string) =>
      ["repositories", "pullRequests", id, { state }] as const,
  },
  pullRequests: {
    all: ["pullRequests"] as const,
    list: (params?: {
      repositoryId?: string;
      state?: string;
      limit?: number;
      offset?: number;
    }) => ["pullRequests", "list", params] as const,
    detail: (id: string) => ["pullRequests", "detail", id] as const,
    reviews: (id: string, status?: string) =>
      ["pullRequests", "reviews", id, { status }] as const,
  },
  reviews: {
    all: ["reviews"] as const,
    list: (params?: {
      pullRequestId?: string;
      status?: string;
      limit?: number;
      offset?: number;
    }) => ["reviews", "list", params] as const,
    detail: (id: string) => ["reviews", "detail", id] as const,
    findings: (
      id: string,
      filters?: {
        verificationStatus?: string;
        severity?: string;
        issueType?: string;
      },
    ) => ["reviews", "findings", id, filters] as const,
    evidence: (id: string) => ["reviews", "evidence", id] as const,
    publications: (id: string) => ["reviews", "publications", id] as const,
    feedback: (id: string) => ["reviews", "feedback", id] as const,
  },
  findings: {
    all: ["findings"] as const,
    list: (params?: {
      reviewRunId?: string;
      verificationStatus?: string;
      severity?: string;
      issueType?: string;
      limit?: number;
      offset?: number;
    }) => ["findings", "list", params] as const,
    detail: (id: string) => ["findings", "detail", id] as const,
    evidence: (id: string) => ["findings", "evidence", id] as const,
  },
  evaluation: {
    summary: ["evaluation", "summary"] as const,
    cases: (category?: string) => ["evaluation", "cases", { category }] as const,
    baselines: ["evaluation", "baselines"] as const,
    livePrs: ["evaluation", "livePrs"] as const,
  },
  feedback: {
    all: ["feedback"] as const,
    list: (filters?: Record<string, unknown>) =>
      ["feedback", "list", filters] as const,
    detail: (id: string) => ["feedback", "detail", id] as const,
  },
};
