import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { fetchReviewRuns } from "@/lib/api/reviews";
import { queryKeys } from "@/lib/query/queryKeys";
import { LoadingState } from "@/components/ui/LoadingState";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { formatDate, formatDuration, truncateSha } from "@/lib/utils/formatters";
import { PlayCircle } from "lucide-react";

export const ReviewRunsPage: React.FC = () => {
  const [statusFilter, setStatusFilter] = useState<string>("ALL");

  const {
    data: runs,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: queryKeys.reviews.list({
      status: statusFilter === "ALL" ? undefined : statusFilter,
    }),
    queryFn: () =>
      fetchReviewRuns({
        status: statusFilter === "ALL" ? undefined : statusFilter,
      }),
  });

  const statuses = ["ALL", "COMPLETED", "RUNNING", "FAILED", "PENDING"];

  return (
    <div>
      <div className="page-header">
        <div>
          <h2 className="page-heading">Review Executions</h2>
          <p className="page-subheading">
            Audit history of automated specialist analysis, critic verification, and GitHub publication
          </p>
        </div>
      </div>

      {/* Status Filter Tabs */}
      <div className="tab-group" style={{ marginBottom: "20px" }}>
        {statuses.map((status) => (
          <button
            key={status}
            onClick={() => setStatusFilter(status)}
            className={`tab-btn ${statusFilter === status ? "active" : ""}`}
            data-testid={`filter-${status.toLowerCase()}`}
          >
            {status}
          </button>
        ))}
      </div>

      {isLoading ? (
        <LoadingState title="Loading Review Runs" description="Fetching review execution logs..." />
      ) : error ? (
        <ErrorState
          title="Failed to Load Review Runs"
          message={error instanceof Error ? error.message : "Error fetching review runs"}
          onRetry={() => refetch()}
        />
      ) : !runs || runs.length === 0 ? (
        <EmptyState
          icon={<PlayCircle size={40} />}
          title="No review runs found"
          description={
            statusFilter === "ALL"
              ? "No review executions have been initiated yet."
              : `No review runs found with status '${statusFilter}'.`
          }
        />
      ) : (
        <div className="card">
          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Repository</th>
                  <th>PR</th>
                  <th>Commit</th>
                  <th>Total Findings</th>
                  <th>Verified</th>
                  <th>Published</th>
                  <th>Duration</th>
                  <th>Started</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id} data-testid={`review-run-row-${run.id}`}>
                    <td>
                      <StatusBadge status={run.status} type="review" />
                    </td>
                    <td>{run.repository_full_name || "—"}</td>
                    <td>
                      {run.pr_number ? (
                        <Link
                          to={`/pull-requests/${run.pull_request_id}`}
                          style={{ color: "var(--primary)", fontWeight: 600 }}
                        >
                          #{run.pr_number}
                        </Link>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="mono">{truncateSha(run.commit_sha)}</td>
                    <td>{run.findings_count}</td>
                    <td>
                      <span className="badge badge-verified">
                        {run.verified_findings_count}
                      </span>
                    </td>
                    <td>
                      <span className="badge badge-published">
                        {run.published_findings_count}
                      </span>
                    </td>
                    <td>{formatDuration(run.latency_seconds)}</td>
                    <td>{formatDate(run.created_at)}</td>
                    <td>
                      <Link
                        to={`/reviews/${run.id}`}
                        className="tab-btn"
                        style={{
                          padding: "4px 10px",
                          fontSize: "12px",
                          background: "var(--bg-surface-elevated)",
                          borderRadius: "var(--radius-sm)",
                        }}
                      >
                        Inspect →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};
