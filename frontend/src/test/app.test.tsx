import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { Layout } from "@/components/layout/Layout";
import { FindingCard } from "@/components/findings/FindingCard";
import { EvidenceCard } from "@/components/evidence/EvidenceCard";
import { FeedbackCard } from "@/components/feedback/FeedbackCard";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { ReviewPipeline } from "@/components/reviews/ReviewPipeline";
import type { ReviewFinding, EvidenceModel, FeedbackResponse, ReviewRunRead } from "@/types/api";

const createTestQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

describe("Phase 6 Review Dashboard - UI & Security Invariants", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  // 1. Application shell renders
  it("renders the application shell navigation and header", () => {
    const queryClient = createTestQueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/dashboard"]}>
          <Layout />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByTestId("app-shell")).toBeInTheDocument();
    expect(screen.getByText("Agentic Reviewer")).toBeInTheDocument();
    expect(screen.getByText("Evidence-Based AI")).toBeInTheDocument();
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Repositories")).toBeInTheDocument();
    expect(screen.getByText("Pull Requests")).toBeInTheDocument();
    expect(screen.getByText("Review Runs")).toBeInTheDocument();
    expect(screen.getByText("Findings")).toBeInTheDocument();
    expect(screen.getByText("Feedback")).toBeInTheDocument();
    expect(screen.getByText("Backend Online")).toBeInTheDocument();
  });

  // 2. Dashboard handles loading state
  it("renders loading state when dashboard metrics are fetching", () => {
    const queryClient = createTestQueryClient();
    // Do not mock fetch yet so query stays pending
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <DashboardPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByText("Loading Review Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Aggregating platform metrics...")).toBeInTheDocument();
  });

  // 3. Finding Card: VERIFIED finding shows publication state
  it("displays verified finding as eligible for GitHub publication", () => {
    const verifiedFinding: ReviewFinding = {
      id: "f-123",
      title: "SQL Injection in User Lookup",
      issue_type: "SECURITY",
      severity: "CRITICAL",
      confidence_score: 0.96,
      file_path: "app/auth/login.py",
      line_number: 42,
      side: "RIGHT",
      explanation: "Unsanitized user input formatted directly into SQL query string.",
      recommendation: "Use parameterized queries with prepared statement bindings.",
      suggested_patch: "cursor.execute('SELECT * FROM users WHERE id = %s', (user_id,))",
      verification_status: "VERIFIED",
      publish_status: "UNPUBLISHED",
      critic_notes: "Exploitable SQL vulnerability verified against AST and database query builder.",
      evidence: [],
    };

    render(<FindingCard finding={verifiedFinding} defaultExpanded={true} />);

    expect(screen.getByText("SQL Injection in User Lookup")).toBeInTheDocument();
    expect(screen.getByText("CRITICAL")).toBeInTheDocument();
    expect(screen.getByText("VERIFIED")).toBeInTheDocument();

    // Publication security invariant: VERIFIED findings show publication eligibility badge
    const pubBadge = screen.getByTestId("publication-eligibility-badge");
    expect(pubBadge).toBeInTheDocument();
    expect(pubBadge).toHaveTextContent("ELIGIBLE TO PUBLISH");
    expect(screen.getByText("Critic Verification Passed")).toBeInTheDocument();
    expect(screen.getByText(/Exploitable SQL vulnerability verified/)).toBeInTheDocument();
  });

  // 4. Finding Card: UNVERIFIED finding does NOT display as publishable
  it("enforces publication invariant: unverified findings display NOT PUBLISHABLE", () => {
    const unverifiedFinding: ReviewFinding = {
      id: "f-789",
      title: "Potential N+1 Query in Loop",
      issue_type: "PERFORMANCE",
      severity: "MEDIUM",
      confidence_score: 0.65,
      file_path: "app/services/user_service.py",
      line_number: 88,
      side: "RIGHT",
      explanation: "Iterative query within loop may cause database latency.",
      recommendation: "Use selectinload or joinedload eager fetching.",
      suggested_patch: null,
      verification_status: "UNVERIFIED",
      publish_status: "UNPUBLISHED",
      critic_notes: null,
      evidence: [],
    };

    render(<FindingCard finding={unverifiedFinding} defaultExpanded={false} />);

    expect(screen.getByText("Potential N+1 Query in Loop")).toBeInTheDocument();
    expect(screen.getByText("UNVERIFIED")).toBeInTheDocument();

    // Must NOT have publication eligibility badge
    expect(screen.queryByTestId("publication-eligibility-badge")).not.toBeInTheDocument();

    // Ineligible badge must be present
    const ineligBadge = screen.getByTestId("publication-ineligible-badge");
    expect(ineligBadge).toBeInTheDocument();
    expect(ineligBadge).toHaveTextContent("NOT PUBLISHABLE");
  });

  // 5. Finding Card: REJECTED finding displays rejection notes correctly
  it("renders rejected finding with critic rejection reason and note", () => {
    const rejectedFinding: ReviewFinding = {
      id: "f-999",
      title: "Unused variable in helper function",
      issue_type: "MAINTAINABILITY",
      severity: "LOW",
      confidence_score: 0.45,
      file_path: "app/utils/helpers.py",
      line_number: 12,
      side: "RIGHT",
      explanation: "Variable appears unused in scope.",
      recommendation: "Remove variable declaration.",
      suggested_patch: null,
      verification_status: "REJECTED",
      publish_status: "SKIPPED",
      critic_notes: "Variable is part of required public API protocol signature.",
      rejection_reason: "SUPPRESSED_FALSE_POSITIVE",
      evidence: [],
    };

    render(<FindingCard finding={rejectedFinding} defaultExpanded={true} />);

    expect(screen.getByText("Unused variable in helper function")).toBeInTheDocument();
    expect(screen.getByText("REJECTED")).toBeInTheDocument();
    expect(screen.getByTestId("publication-ineligible-badge")).toBeInTheDocument();
    expect(screen.getByText("Critic Rejection Note")).toBeInTheDocument();
    expect(screen.getByText(/Reason: SUPPRESSED_FALSE_POSITIVE/)).toBeInTheDocument();
    expect(screen.getByText(/Variable is part of required public API/)).toBeInTheDocument();
  });

  // 6. Evidence rendering
  it("renders evidence grounding cards with corroborating tool and snippet", () => {
    const evidence: EvidenceModel = {
      evidence_type: "STATIC_ANALYSIS",
      corroborating_tool: "semgrep",
      rule_or_cve_id: "python.lang.security.audit.sqli",
      file_path: "app/auth/login.py",
      start_line: 40,
      end_line: 45,
      snippet: "cursor.execute(f\"SELECT * FROM users WHERE username = '{username}'\")",
    };

    render(<EvidenceCard evidence={evidence} />);

    expect(screen.getByTestId("evidence-item-static_analysis")).toBeInTheDocument();
    expect(screen.getByText("STATIC_ANALYSIS")).toBeInTheDocument();
    expect(screen.getByText(/semgrep/)).toBeInTheDocument();
    expect(screen.getByText(/python.lang.security.audit.sqli/)).toBeInTheDocument();
    expect(screen.getByText(/app\/auth\/login.py:40–45/)).toBeInTheDocument();
    expect(screen.getByText(/cursor.execute\(f"SELECT/)).toBeInTheDocument();
  });

  it("renders evidence card with all fields including CVE, commit SHA, and content_snippet", () => {
    const evidence: EvidenceModel = {
      id: "ev-uuid-1234",
      evidence_type: "STATIC_ANALYSIS",
      corroborating_tool: "bandit",
      rule_or_cve_id: "CVE-2023-12345",
      file_path: "backend/app/auth.py",
      start_line: 34,
      end_line: 36,
      snippet: "",
      content_snippet: "hashlib.md5(password.encode()).hexdigest()",
      metadata: {
        commit_sha: "af0f0427252487b6cd0b76bba14a0d611fd67024",
      },
    };

    render(<EvidenceCard evidence={evidence} />);

    expect(screen.getByText("STATIC_ANALYSIS")).toBeInTheDocument();
    expect(screen.getByText(/bandit/)).toBeInTheDocument();
    expect(screen.getByText(/CVE-2023-12345/)).toBeInTheDocument();
    expect(screen.getByText(/backend\/app\/auth.py:34–36/)).toBeInTheDocument();
    expect(screen.getByText("af0f042")).toBeInTheDocument();
    expect(screen.getByText(/hashlib.md5/)).toBeInTheDocument();
  });

  it("renders explicit 'Code snippet unavailable' when evidence snippet is empty or unavailable", () => {
    const evidence: EvidenceModel = {
      evidence_type: "DEPENDENCY",
      corroborating_tool: "pip-audit",
      rule_or_cve_id: "GHSA-xxxx-yyyy",
      file_path: "requirements.txt",
      start_line: 12,
      end_line: 12,
      snippet: "   ",
    };

    render(<EvidenceCard evidence={evidence} />);

    expect(screen.getByText("Code snippet unavailable")).toBeInTheDocument();
  });

  // 7. FeedbackCard rendering
  it("renders developer feedback card with reaction and reviewer", () => {
    const feedback: FeedbackResponse = {
      id: "fb-101",
      finding_id: "f-123",
      review_run_id: "run-456",
      repository_id: 1,
      pr_number: 42,
      github_comment_id: 998877,
      github_review_id: null,
      feedback_type: "REACTION_POSITIVE",
      feedback_source: "GITHUB_WEBHOOK",
      reviewer_username: "octocat",
      comment_body: "Great catch on the SQL injection!",
      extra_metadata: { reaction: "+1" },
      created_at: new Date().toISOString(),
    };

    render(<FeedbackCard feedback={feedback} />);

    expect(screen.getByTestId("feedback-item-fb-101")).toBeInTheDocument();
    expect(screen.getByText("REACTION POSITIVE")).toBeInTheDocument();
    expect(screen.getByText("GITHUB_WEBHOOK")).toBeInTheDocument();
    expect(screen.getByText(/octocat/)).toBeInTheDocument();
    expect(screen.getByText(/Comment #998877/)).toBeInTheDocument();
    expect(screen.getByText(/"Great catch on the SQL injection!"/)).toBeInTheDocument();
  });

  // 8. ReviewPipeline rendering
  it("renders visual pipeline steps with verification and publication metrics", () => {
    const mockRun: ReviewRunRead = {
      id: "run-777",
      pull_request_id: "pr-1",
      pr_number: 14,
      repository_full_name: "acme/repo",
      commit_sha: "abcdef1234567890abcdef1234567890abcdef12",
      status: "COMPLETED",
      trigger_type: "PULL_REQUEST",
      total_tokens: 4200,
      total_cost_usd: 0.0125,
      latency_seconds: 14.2,
      review_plan: {
        review_scope: "FULL",
        active_agents: ["security", "performance"],
        target_files: ["app/main.py"],
      },
      error_log: null,
      started_at: new Date().toISOString(),
      completed_at: new Date().toISOString(),
      created_at: new Date().toISOString(),
      findings_count: 5,
      verified_findings_count: 3,
      published_findings_count: 3,
    };

    render(<ReviewPipeline run={mockRun} />);

    const pipeline = screen.getByTestId("review-pipeline");
    expect(pipeline).toBeInTheDocument();
    expect(screen.getByText("PR Ingested")).toBeInTheDocument();
    expect(screen.getByText("Planner")).toBeInTheDocument();
    expect(screen.getByText("Specialists")).toBeInTheDocument();
    expect(screen.getByText("Critic")).toBeInTheDocument();
    expect(screen.getByText("Verified (3)")).toBeInTheDocument();
    expect(screen.getByText("Published (3)")).toBeInTheDocument();
  });

  it("faithfully marks pipeline steps completed even when status is lowercase 'completed'", () => {
    const lowercaseRun: ReviewRunRead = {
      id: "run-888",
      pull_request_id: "pr-2",
      pr_number: 15,
      repository_full_name: "acme/repo",
      commit_sha: "1234567890abcdef1234567890abcdef12345678",
      status: "completed",
      trigger_type: "WEBHOOK",
      total_tokens: 1200,
      total_cost_usd: 0.005,
      latency_seconds: 8.5,
      review_plan: {
        review_scope: "FULL",
        active_agents: ["security"],
        target_files: ["app/auth.py"],
      },
      error_log: null,
      started_at: new Date().toISOString(),
      completed_at: new Date().toISOString(),
      created_at: new Date().toISOString(),
      findings_count: 1,
      verified_findings_count: 1,
      published_findings_count: 1,
    };

    render(<ReviewPipeline run={lowercaseRun} />);

    const pipeline = screen.getByTestId("review-pipeline");
    expect(pipeline).toBeInTheDocument();
    // All steps should have completed class
    const steps = pipeline.querySelectorAll(".pipeline-step");
    expect(steps.length).toBe(7);
    steps.forEach((step) => {
      expect(step).toHaveClass("completed");
    });
  });

  it("correctly renders queued review with downstream steps pending", () => {
    const queuedRun: ReviewRunRead = {
      id: "run-queued",
      pull_request_id: "pr-queued",
      pr_number: 101,
      repository_full_name: "acme/repo",
      commit_sha: "aaaabbbbcccc",
      status: "QUEUED",
      trigger_type: "WEBHOOK",
      total_tokens: 0,
      total_cost_usd: 0,
      latency_seconds: null,
      review_plan: null,
      error_log: null,
      started_at: null,
      completed_at: null,
      created_at: new Date().toISOString(),
      findings_count: 0,
      verified_findings_count: 0,
      published_findings_count: 0,
    };

    render(<ReviewPipeline run={queuedRun} />);
    const pipeline = screen.getByTestId("review-pipeline");
    const steps = pipeline.querySelectorAll(".pipeline-step");
    expect(steps[0]).toHaveClass("completed"); // PR Ingested
    expect(steps[1]).toHaveClass("pending"); // Planner
    expect(steps[2]).toHaveClass("pending"); // Specialists
    expect(steps[3]).toHaveClass("pending"); // Evidence
    expect(steps[4]).toHaveClass("pending"); // Critic
  });

  it("correctly renders running review with active stage", () => {
    const runningRun: ReviewRunRead = {
      id: "run-running",
      pull_request_id: "pr-running",
      pr_number: 102,
      repository_full_name: "acme/repo",
      commit_sha: "bbbbccccdddd",
      status: "RUNNING",
      trigger_type: "WEBHOOK",
      total_tokens: 500,
      total_cost_usd: 0.001,
      latency_seconds: null,
      review_plan: null,
      error_log: null,
      started_at: new Date().toISOString(),
      completed_at: null,
      created_at: new Date().toISOString(),
      findings_count: 0,
      verified_findings_count: 0,
      published_findings_count: 0,
    };

    render(<ReviewPipeline run={runningRun} />);
    const pipeline = screen.getByTestId("review-pipeline");
    const steps = pipeline.querySelectorAll(".pipeline-step");
    expect(steps[0]).toHaveClass("completed");
    expect(steps[1]).toHaveClass("active"); // Planner active
  });

  it("correctly renders failed review with failed step visibly distinguished", () => {
    const failedRun: ReviewRunRead = {
      id: "run-failed",
      pull_request_id: "pr-failed",
      pr_number: 103,
      repository_full_name: "acme/repo",
      commit_sha: "ccccddddeeee",
      status: "FAILED",
      trigger_type: "WEBHOOK",
      total_tokens: 100,
      total_cost_usd: 0.0005,
      latency_seconds: null,
      review_plan: null,
      error_log: "Fatal error in planner",
      started_at: new Date().toISOString(),
      completed_at: null,
      created_at: new Date().toISOString(),
      findings_count: 0,
      verified_findings_count: 0,
      published_findings_count: 0,
    };

    render(<ReviewPipeline run={failedRun} />);
    const pipeline = screen.getByTestId("review-pipeline");
    const steps = pipeline.querySelectorAll(".pipeline-step");
    expect(steps[0]).toHaveClass("completed");
    expect(steps[1]).toHaveClass("failed"); // Planner failed
    expect(pipeline.querySelector(".failed")).toBeInTheDocument();
  });

  it("correctly reflects review with zero findings and rejected findings", () => {
    const rejectedFindingsRun: ReviewRunRead = {
      id: "run-rejected",
      pull_request_id: "pr-rejected",
      pr_number: 104,
      repository_full_name: "acme/repo",
      commit_sha: "ddddeeeeffff",
      status: "COMPLETED",
      trigger_type: "WEBHOOK",
      total_tokens: 3000,
      total_cost_usd: 0.008,
      latency_seconds: 12.0,
      review_plan: {
        review_scope: "FULL",
        active_agents: ["security"],
        target_files: ["main.py"],
      },
      error_log: null,
      started_at: new Date().toISOString(),
      completed_at: new Date().toISOString(),
      created_at: new Date().toISOString(),
      findings_count: 4,
      verified_findings_count: 0, // all rejected by critic
      published_findings_count: 0, // none published
    };

    render(<ReviewPipeline run={rejectedFindingsRun} />);
    expect(screen.getByText("Verified (0)")).toBeInTheDocument();
    expect(screen.getByText("Published (0)")).toBeInTheDocument();
  });

  // 9. Security: Sensitive tokens/passwords must NEVER be rendered
  it("ensures no private credentials or secret keys are rendered in DOM", () => {
    const queryClient = createTestQueryClient();
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <Layout />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const htmlContent = container.innerHTML;
    expect(htmlContent).not.toContain("ghp_");
    expect(htmlContent).not.toContain("github_pat_");
    expect(htmlContent).not.toContain("PRIVATE KEY");
    expect(htmlContent).not.toContain("DATABASE_URL");
    expect(htmlContent).not.toContain("REDIS_URL");
    expect(htmlContent).not.toContain("GEMINI_API_KEY");
  });

  // 10. Dashboard handles API error
  it("renders ErrorState when dashboard metrics query fails", async () => {
    const queryClient = createTestQueryClient();
    global.fetch = vi.fn().mockRejectedValue(new Error("Database connection down"));

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <DashboardPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const errorHeading = await screen.findByText("Failed to Load Dashboard Metrics");
    expect(errorHeading).toBeInTheDocument();
    expect(screen.getByText("Database connection down")).toBeInTheDocument();
    expect(screen.getByText("Try Again")).toBeInTheDocument();
  });

  // 11. Dashboard renders with real metrics and empty runs
  it("renders metrics stat cards and empty state when runs are empty", async () => {
    const queryClient = createTestQueryClient();
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/dashboard/metrics")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            total_repositories: 2,
            total_pull_requests: 5,
            total_review_runs: 10,
            active_review_runs: 1,
            total_findings: 18,
            verified_findings: 12,
            rejected_findings: 6,
            published_findings: 8,
            total_feedback_events: 4,
          }),
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => [],
      });
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <DashboardPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Tracked Repositories")).toBeInTheDocument();
    expect(screen.getByText("Total Findings")).toBeInTheDocument();
    expect(screen.getByText("Verified Findings")).toBeInTheDocument();
    expect(screen.getByText("Published Comments")).toBeInTheDocument();
    expect(screen.getByText("No review runs executed yet")).toBeInTheDocument();
  });
});

