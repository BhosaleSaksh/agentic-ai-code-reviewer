import React from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { fetchPullRequestById, fetchPullRequestReviews } from "@/lib/api/pullRequests";
import { queryKeys } from "@/lib/query/queryKeys";
import { LoadingState } from "@/components/ui/LoadingState";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { formatDate, formatDuration, truncateSha } from "@/lib/utils/formatters";
import { CheckCircle2, ArrowRight } from "lucide-react";

export const PullRequestDetailPage: React.FC = () => {
  const { pullRequestId } = useParams<{ pullRequestId: string }>();

  const {
    data: pr,
    isLoading: isLoadingPr,
    error: prError,
  } = useQuery({
    queryKey: queryKeys.pullRequests.detail(pullRequestId || ""),
    queryFn: () => fetchPullRequestById(pullRequestId || ""),
    enabled: !!pullRequestId,
  });

  const {
    data: reviews,
    isLoading: isLoadingReviews,
  } = useQuery({
    queryKey: queryKeys.pullRequests.reviews(pullRequestId || ""),
    queryFn: () => fetchPullRequestReviews(pullRequestId || ""),
    enabled: !!pullRequestId,
  });

  if (isLoadingPr) {
    return <LoadingState title="Loading Pull Request" description="Fetching PR metadata and review executions..." />;
  }

  if (prError || !pr) {
    return (
      <ErrorState
        title="Pull Request Not Found"
        message={prError instanceof Error ? prError.message : "The requested pull request could not be found."}
      />
    );
  }

  const latestReview = reviews && reviews.length > 0 ? reviews[0] : null;

  return (
    <div>
      <div className="page-header">
        <div>
          <div style={{ marginBottom: "6px" }}>
            <Link to="/pull-requests" style={{ color: "var(--text-muted)", fontSize: "13px" }}>
              ← Back to Pull Requests
            </Link>
          </div>
          <h2 className="page-heading">
            {pr.repository_full_name ? `${pr.repository_full_name} ` : ""}PR #{pr.pr_number}: {pr.title}
          </h2>
          <p className="page-subheading">
            Author: {pr.author} • State: <StatusBadge status={pr.state} /> • Base: {truncateSha(pr.base_sha)} → Head: {truncateSha(pr.head_sha)}
          </p>
        </div>

        {latestReview && (
          <Link
            to={`/reviews/${latestReview.id}`}
            className="tab-btn active"
            style={{ borderRadius: "var(--radius-md)", padding: "8px 16px" }}
          >
            View Latest Review Run →
          </Link>
        )}
      </div>

      {/* Review Lifecycle Pipeline Visualizer (Step 7) */}
      <div className="card">
        <h4 className="card-title" style={{ marginBottom: "12px" }}>Pull Request Review Lifecycle</h4>
        <div className="pipeline-flow" aria-label="PR Lifecycle Flow">
          <div className="pipeline-step completed">
            <CheckCircle2 size={14} color="#10b981" />
            <span>1. PR Ingested</span>
          </div>
          <ArrowRight size={14} className="pipeline-arrow" />

          <div className={`pipeline-step ${reviews && reviews.length > 0 ? "completed" : "pending"}`}>
            <span>2. Analysis & Specialists</span>
          </div>
          <ArrowRight size={14} className="pipeline-arrow" />

          <div className={`pipeline-step ${latestReview && latestReview.verified_findings_count > 0 ? "completed" : "pending"}`}>
            <span>3. Critic Verified</span>
          </div>
          <ArrowRight size={14} className="pipeline-arrow" />

          <div className={`pipeline-step ${latestReview && latestReview.published_findings_count > 0 ? "completed" : "pending"}`}>
            <span>4. Published to GitHub</span>
          </div>
        </div>
      </div>

      {/* Review Executions Table */}
      <div className="card">
        <div className="card-header">
          <h3 className="card-title">Review Runs Triggered ({reviews?.length || 0})</h3>
        </div>

        {isLoadingReviews ? (
          <LoadingState description="Loading review executions..." />
        ) : !reviews || reviews.length === 0 ? (
          <EmptyState
            title="No review runs executed yet"
            description="When review jobs run for this PR, execution details and findings will appear here."
          />
        ) : (
          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Commit</th>
                  <th>Findings</th>
                  <th>Verified</th>
                  <th>Published</th>
                  <th>Cost</th>
                  <th>Latency</th>
                  <th>Started</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {reviews.map((rev) => (
                  <tr key={rev.id}>
                    <td>
                      <StatusBadge status={rev.status} type="review" />
                    </td>
                    <td className="mono">{truncateSha(rev.commit_sha)}</td>
                    <td>{rev.findings_count}</td>
                    <td>
                      <span className="badge badge-verified">{rev.verified_findings_count}</span>
                    </td>
                    <td>
                      <span className="badge badge-published">{rev.published_findings_count}</span>
                    </td>
                    <td>${rev.total_cost_usd.toFixed(4)}</td>
                    <td>{formatDuration(rev.latency_seconds)}</td>
                    <td>{formatDate(rev.started_at || rev.created_at)}</td>
                    <td>
                      <Link
                        to={`/reviews/${rev.id}`}
                        className="tab-btn"
                        style={{ padding: "4px 10px", fontSize: "12px", background: "var(--bg-surface-elevated)", borderRadius: "var(--radius-sm)" }}
                      >
                        Inspect Run
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
