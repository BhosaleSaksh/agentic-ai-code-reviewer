import React, { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  fetchReviewRunById,
  fetchReviewRunFindings,
  fetchReviewRunEvidence,
  fetchReviewRunPublications,
  fetchReviewRunFeedback,
} from "@/lib/api/reviews";
import { queryKeys } from "@/lib/query/queryKeys";
import { LoadingState } from "@/components/ui/LoadingState";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ReviewPipeline } from "@/components/reviews/ReviewPipeline";
import { FindingCard } from "@/components/findings/FindingCard";
import { EvidenceCard } from "@/components/evidence/EvidenceCard";
import { FeedbackCard } from "@/components/feedback/FeedbackCard";
import { formatDate, formatDuration, truncateSha } from "@/lib/utils/formatters";
import {
  Layers,
  FileSearch,
  Send,
  MessageSquareQuote,
  ShieldCheck,
  CheckCircle2,
} from "lucide-react";

export const ReviewRunDetailPage: React.FC = () => {
  const { reviewRunId } = useParams<{ reviewRunId: string }>();
  const [activeTab, setActiveTab] = useState<"findings" | "evidence" | "publications" | "feedback">("findings");
  const [findingFilter, setFindingFilter] = useState<string>("ALL");

  const {
    data: run,
    isLoading: isLoadingRun,
    error: runError,
    refetch: refetchRun,
  } = useQuery({
    queryKey: queryKeys.reviews.detail(reviewRunId || ""),
    queryFn: () => fetchReviewRunById(reviewRunId || ""),
    enabled: !!reviewRunId,
  });

  const {
    data: findings,
    isLoading: isLoadingFindings,
  } = useQuery({
    queryKey: queryKeys.reviews.findings(reviewRunId || "", {
      verificationStatus: findingFilter === "ALL" ? undefined : findingFilter,
    }),
    queryFn: () =>
      fetchReviewRunFindings(reviewRunId || "", {
        verificationStatus: findingFilter === "ALL" ? undefined : findingFilter,
      }),
    enabled: !!reviewRunId,
  });

  const {
    data: evidenceList,
    isLoading: isLoadingEvidence,
  } = useQuery({
    queryKey: queryKeys.reviews.evidence(reviewRunId || ""),
    queryFn: () => fetchReviewRunEvidence(reviewRunId || ""),
    enabled: !!reviewRunId && activeTab === "evidence",
  });

  const {
    data: publications,
    isLoading: isLoadingPublications,
  } = useQuery({
    queryKey: queryKeys.reviews.publications(reviewRunId || ""),
    queryFn: () => fetchReviewRunPublications(reviewRunId || ""),
    enabled: !!reviewRunId && activeTab === "publications",
  });

  const {
    data: feedbackList,
    isLoading: isLoadingFeedback,
  } = useQuery({
    queryKey: queryKeys.reviews.feedback(reviewRunId || ""),
    queryFn: () => fetchReviewRunFeedback(reviewRunId || ""),
    enabled: !!reviewRunId && activeTab === "feedback",
  });

  if (isLoadingRun) {
    return <LoadingState title="Loading Review Execution" description="Fetching run details and pipeline state..." />;
  }

  if (runError || !run) {
    return (
      <ErrorState
        title="Failed to Load Review Run"
        message={runError instanceof Error ? runError.message : "Run not found"}
        onRetry={() => refetchRun()}
      />
    );
  }

  return (
    <div>
      {/* Header & Run Context */}
      <div className="page-header">
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "6px" }}>
            <StatusBadge status={run.status} type="review" />
            <span style={{ fontSize: "12px", color: "var(--text-muted)", fontFamily: "JetBrains Mono" }}>
              ID: {run.id}
            </span>
          </div>
          <h2 className="page-heading">
            Review for PR #{run.pr_number} ({run.repository_full_name || "Repository"})
          </h2>
          <p className="page-subheading">
            Targeting commit <span className="mono">{truncateSha(run.commit_sha)}</span> • Started {formatDate(run.created_at)}
          </p>
        </div>

        <div style={{ display: "flex", gap: "8px" }}>
          {run.pull_request_id && (
            <Link
              to={`/pull-requests/${run.pull_request_id}`}
              className="tab-btn"
              style={{ padding: "8px 14px", background: "var(--bg-surface-elevated)" }}
            >
              View PR #{run.pr_number} →
            </Link>
          )}
        </div>
      </div>

      {/* Visual Agentic Pipeline Flow */}
      <div className="card" style={{ marginBottom: "20px" }}>
        <div className="card-header" style={{ marginBottom: "12px" }}>
          <h3 className="card-title" style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <ShieldCheck size={18} color="var(--primary)" />
            Agentic Review Execution Pipeline
          </h3>
          <span style={{ fontSize: "12px", color: "var(--text-muted)" }}>
            Duration: {formatDuration(run.latency_seconds)}
          </span>
        </div>
        <ReviewPipeline run={run} />
      </div>

      {/* Review Plan Summary Card (if available) */}
      {run.review_plan && (
        <div className="card" style={{ marginBottom: "20px" }}>
          <div className="card-header" style={{ marginBottom: "8px" }}>
            <h4 className="card-title" style={{ fontSize: "14px" }}>
              Review Planner Strategy
            </h4>
            <span className="badge badge-info">{run.review_plan.review_scope || "FULL"}</span>
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "16px", fontSize: "12px", color: "var(--text-muted)" }}>
            <div>
              <strong>Active Agents:</strong>{" "}
              {run.review_plan.active_agents?.join(", ") || "General"}
            </div>
            <div>
              <strong>Target Files:</strong> {run.review_plan.target_files?.length ?? 0} files
            </div>
            {run.review_plan.focus_areas && run.review_plan.focus_areas.length > 0 && (
              <div>
                <strong>Focus Areas:</strong> {run.review_plan.focus_areas.join(", ")}
              </div>
            )}
            {run.review_plan.is_large_pr && (
              <div>
                <span className="badge badge-warning">Large PR (&gt;400 LOC)</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Tabs Navigation */}
      <div className="tab-group" style={{ marginBottom: "20px" }}>
        <button
          onClick={() => setActiveTab("findings")}
          className={`tab-btn ${activeTab === "findings" ? "active" : ""}`}
          data-testid="tab-findings"
        >
          <Layers size={14} style={{ marginRight: "6px" }} />
          Findings ({run.findings_count})
        </button>
        <button
          onClick={() => setActiveTab("evidence")}
          className={`tab-btn ${activeTab === "evidence" ? "active" : ""}`}
          data-testid="tab-evidence"
        >
          <FileSearch size={14} style={{ marginRight: "6px" }} />
          Evidence Grounding
        </button>
        <button
          onClick={() => setActiveTab("publications")}
          className={`tab-btn ${activeTab === "publications" ? "active" : ""}`}
          data-testid="tab-publications"
        >
          <Send size={14} style={{ marginRight: "6px" }} />
          GitHub Publications ({run.published_findings_count})
        </button>
        <button
          onClick={() => setActiveTab("feedback")}
          className={`tab-btn ${activeTab === "feedback" ? "active" : ""}`}
          data-testid="tab-feedback"
        >
          <MessageSquareQuote size={14} style={{ marginRight: "6px" }} />
          Developer Feedback
        </button>
      </div>

      {/* TAB CONTENT: Findings */}
      {activeTab === "findings" && (
        <div>
          {/* Sub-filter tabs */}
          <div style={{ display: "flex", gap: "8px", marginBottom: "16px" }}>
            {["ALL", "VERIFIED", "REJECTED", "UNVERIFIED"].map((f) => (
              <button
                key={f}
                onClick={() => setFindingFilter(f)}
                className={`tab-btn ${findingFilter === f ? "active" : ""}`}
                style={{ fontSize: "12px", padding: "4px 10px" }}
              >
                {f}
              </button>
            ))}
          </div>

          {isLoadingFindings ? (
            <LoadingState description="Loading findings..." />
          ) : !findings || findings.length === 0 ? (
            <EmptyState
              icon={<CheckCircle2 size={36} />}
              title="No findings matched the criteria"
              description="Either no issues were discovered, or all findings were suppressed during critic verification."
            />
          ) : (
            <div className="findings-list">
              {findings.map((f) => (
                <FindingCard key={f.id} finding={f} defaultExpanded={f.verification_status === "VERIFIED"} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* TAB CONTENT: Evidence Grounding */}
      {activeTab === "evidence" && (
        <div>
          {isLoadingEvidence ? (
            <LoadingState description="Retrieving evidence grounding artifacts..." />
          ) : !evidenceList || evidenceList.length === 0 ? (
            <EmptyState
              icon={<FileSearch size={36} />}
              title="No explicit evidence records found"
              description="Evidence items linked to this review run will appear here."
            />
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
              {evidenceList.map((ev, idx) => (
                <EvidenceCard key={`${ev.file_path}-${ev.start_line}-${idx}`} evidence={ev} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* TAB CONTENT: GitHub Publications */}
      {activeTab === "publications" && (
        <div className="card">
          <div className="card-header">
            <h3 className="card-title">GitHub PR Publication Audits</h3>
            <span className="badge badge-published">
              {run.published_findings_count} Comments Posted
            </span>
          </div>

          {isLoadingPublications ? (
            <LoadingState description="Loading publication records..." />
          ) : !publications || publications.length === 0 ? (
            <EmptyState
              icon={<Send size={36} />}
              title="No publication audits available"
              description="Only verified findings are published to GitHub PR inline threads."
            />
          ) : (
            <div className="table-container">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Status</th>
                    <th>Comment ID</th>
                    <th>Commit SHA</th>
                    <th>Published At</th>
                    <th>Reason / Details</th>
                  </tr>
                </thead>
                <tbody>
                  {publications.map((pub, idx) => (
                    <tr key={pub.github_comment_id || pub.idempotency_key || idx}>
                      <td>
                        <StatusBadge status={pub.status} type="publication" />
                      </td>
                      <td>{pub.github_comment_id ? `#${pub.github_comment_id}` : pub.github_review_id ? `Review #${pub.github_review_id}` : "—"}</td>
                      <td className="mono">{truncateSha(run.commit_sha)}</td>
                      <td>{pub.published_at ? formatDate(pub.published_at) : "—"}</td>
                      <td style={{ fontSize: "12px", color: pub.failure_message ? "var(--warning)" : "var(--text-muted)" }}>
                        {pub.failure_message || (pub.status === "PUBLISHED" ? "Published successfully" : "Pending or skipped")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* TAB CONTENT: Developer Feedback */}
      {activeTab === "feedback" && (
        <div>
          {isLoadingFeedback ? (
            <LoadingState description="Loading developer feedback events..." />
          ) : !feedbackList || feedbackList.length === 0 ? (
            <EmptyState
              icon={<MessageSquareQuote size={36} />}
              title="No developer feedback recorded"
              description="Reactions and replies posted to published GitHub comments will be captured here."
            />
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
              {feedbackList.map((fb) => (
                <FeedbackCard key={fb.id} feedback={fb} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
