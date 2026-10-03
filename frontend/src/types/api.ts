/**
 * Canonical TypeScript types mirroring backend FastAPI/Pydantic schemas.
 *
 * Enforces strict typing across all frontend API consumers, state management,
 * and presentation components.
 */

export type Severity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";

export type IssueType =
  | "SECURITY"
  | "BUG_LOGIC"
  | "ERROR_HANDLING"
  | "TEST_ADEQUACY"
  | "PERFORMANCE"
  | "MAINTAINABILITY";

export type FindingSide = "RIGHT" | "LEFT";

export type VerificationStatus =
  | "UNVERIFIED"
  | "VERIFIED"
  | "REJECTED"
  | "SUPPRESSED_FALSE_POSITIVE"
  | "DROPPED_LOW_CONFIDENCE";

export type PublishStatus =
  | "UNPUBLISHED"
  | "PUBLISHED"
  | "FAILED"
  | "DISMISSED"
  | "SKIPPED";

export type EvidenceType =
  | "DIFF_HUNK"
  | "STATIC_ANALYSIS"
  | "DEPENDENCY"
  | "AST_CONTEXT";

export type FeedbackType =
  | "REACTION_POSITIVE"
  | "REACTION_NEGATIVE"
  | "COMMENT_REPLY"
  | "COMMENT_DISMISSED"
  | "FINDING_ACCEPTED"
  | "FINDING_REJECTED"
  | "REVIEW_SUBMITTED";

export type FeedbackSource = "GITHUB_WEBHOOK" | "DASHBOARD_UI" | "CLI_TOOL";

export interface EvidenceModel {
  evidence_type: EvidenceType;
  file_path: string;
  start_line: number;
  end_line: number;
  snippet: string;
  rule_or_cve_id: string | null;
  corroborating_tool: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface ReviewFinding {
  id: string;
  issue_type: IssueType;
  severity: Severity;
  file_path: string;
  line_number: number;
  side: FindingSide;
  title: string;
  explanation: string;
  recommendation: string;
  suggested_patch?: string | null;
  confidence_score: number;
  raw_confidence?: number | null;
  verification_status: VerificationStatus;
  critic_notes?: string | null;
  agent_name?: string | null;
  rejection_reason?: string | null;
  publish_status: PublishStatus;
  github_comment_id?: number | null;
  evidence: EvidenceModel[];
}

export interface RepositoryRead {
  id: string;
  github_repo_id: number;
  full_name: string;
  default_branch: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  pull_requests_count: number;
}

export interface PullRequestRead {
  id: string;
  repository_id: string;
  repository_full_name: string | null;
  pr_number: number;
  title: string;
  author: string;
  base_sha: string;
  head_sha: string;
  state: string;
  additions: number;
  deletions: number;
  changed_files_count: number;
  created_at: string;
  updated_at: string;
  review_runs_count: number;
  latest_review_run_id: string | null;
  latest_review_run_status: string | null;
}

export interface ReviewPlanData {
  review_scope?: string;
  active_agents?: string[];
  focus_areas?: string[];
  target_files?: string[];
  is_large_pr?: boolean;
  [key: string]: unknown;
}

export interface ReviewRunRead {
  id: string;
  pull_request_id: string;
  pr_number: number | null;
  repository_full_name: string | null;
  commit_sha: string;
  status: "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED" | string;
  trigger_type: string;
  total_tokens: number;
  total_cost_usd: number;
  latency_seconds: number | null;
  review_plan: ReviewPlanData | null;
  error_log: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  findings_count: number;
  verified_findings_count: number;
  published_findings_count: number;
}

export interface DashboardMetrics {
  total_repositories: number;
  total_pull_requests: number;
  total_review_runs: number;
  active_review_runs: number;
  total_findings: number;
  verified_findings: number;
  rejected_findings: number;
  published_findings: number;
  total_feedback_events: number;
}

export interface PublicationResult {
  finding_id: string | null;
  idempotency_key: string;
  status: PublishStatus;
  github_comment_id: number | null;
  github_review_id: number | null;
  published_at: string | null;
  failure_category: string | null;
  failure_message: string | null;
  is_duplicate: boolean;
}

export interface FeedbackResponse {
  id: string;
  finding_id: string | null;
  review_run_id: string | null;
  repository_id: number;
  pr_number: number;
  github_comment_id: number | null;
  github_review_id: number | null;
  feedback_type: FeedbackType;
  feedback_source: FeedbackSource;
  reviewer_username: string | null;
  comment_body: string | null;
  extra_metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface ApiErrorResponse {
  message: string;
  statusCode: number;
  detail?: string | unknown;
}
