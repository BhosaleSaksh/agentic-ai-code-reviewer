import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { fetchPullRequests } from "@/lib/api/pullRequests";
import { queryKeys } from "@/lib/query/queryKeys";
import { LoadingState } from "@/components/ui/LoadingState";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { formatDate, truncateSha } from "@/lib/utils/formatters";

export const PullRequestsPage: React.FC = () => {
  const [stateFilter, setStateFilter] = useState<string>("");

  const {
    data: pullRequests,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: queryKeys.pullRequests.list({ state: stateFilter || undefined }),
    queryFn: () => fetchPullRequests({ state: stateFilter || undefined }),
  });

  if (isLoading) {
    return <LoadingState title="Loading Pull Requests" description="Fetching PR records from review queue..." />;
  }

  if (error) {
    return (
      <ErrorState
        title="Failed to Load Pull Requests"
        message={error instanceof Error ? error.message : "Error fetching pull requests"}
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h2 className="page-heading">Pull Requests</h2>
          <p className="page-subheading">
            Ingested pull requests and automated review status
          </p>
        </div>

        <div className="filter-bar" style={{ marginBottom: 0 }}>
          <select
            className="filter-select"
            value={stateFilter}
            onChange={(e) => setStateFilter(e.target.value)}
            aria-label="Filter by state"
          >
            <option value="">All States</option>
            <option value="open">Open</option>
            <option value="closed">Closed</option>
          </select>
        </div>
      </div>

      {!pullRequests || pullRequests.length === 0 ? (
        <EmptyState
          title="No pull requests found"
          description="Pull requests received via GitHub webhooks will be listed here."
        />
      ) : (
        <div className="table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>PR #</th>
                <th>Repository</th>
                <th>Title</th>
                <th>Author</th>
                <th>State</th>
                <th>Commit</th>
                <th>Changes</th>
                <th>Reviews</th>
                <th>Latest Status</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {pullRequests.map((pr) => (
                <tr key={pr.id} data-testid={`pr-row-${pr.id}`}>
                  <td>
                    <Link
                      to={`/pull-requests/${pr.id}`}
                      style={{ color: "var(--primary)", fontWeight: 700 }}
                    >
                      #{pr.pr_number}
                    </Link>
                  </td>
                  <td>{pr.repository_full_name || "—"}</td>
                  <td style={{ fontWeight: 500 }}>{pr.title}</td>
                  <td>{pr.author}</td>
                  <td>
                    <StatusBadge status={pr.state} />
                  </td>
                  <td className="mono">{truncateSha(pr.head_sha)}</td>
                  <td>
                    <span style={{ color: "#10b981", marginRight: "6px" }}>+{pr.additions}</span>
                    <span style={{ color: "#ef4444" }}>-{pr.deletions}</span>
                  </td>
                  <td>{pr.review_runs_count}</td>
                  <td>
                    {pr.latest_review_run_id ? (
                      <Link to={`/reviews/${pr.latest_review_run_id}`}>
                        <StatusBadge status={pr.latest_review_run_status} type="review" />
                      </Link>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>{formatDate(pr.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
