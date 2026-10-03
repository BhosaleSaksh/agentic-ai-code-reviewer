import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { fetchRepositories } from "@/lib/api/repositories";
import { queryKeys } from "@/lib/query/queryKeys";
import { LoadingState } from "@/components/ui/LoadingState";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { formatDate } from "@/lib/utils/formatters";

export const RepositoriesPage: React.FC = () => {
  const {
    data: repositories,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: queryKeys.repositories.list(),
    queryFn: () => fetchRepositories(),
  });

  if (isLoading) {
    return <LoadingState title="Loading Repositories" description="Fetching registered repositories..." />;
  }

  if (error) {
    return (
      <ErrorState
        title="Failed to Load Repositories"
        message={error instanceof Error ? error.message : "Error connecting to repository API"}
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h2 className="page-heading">Tracked Repositories</h2>
          <p className="page-subheading">
            Repositories monitored for pull request review automation
          </p>
        </div>
      </div>

      {!repositories || repositories.length === 0 ? (
        <EmptyState
          title="No repositories registered"
          description="When GitHub App webhooks are received or repositories are added, they will appear here."
        />
      ) : (
        <div className="table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>Repository</th>
                <th>GitHub ID</th>
                <th>Default Branch</th>
                <th>Status</th>
                <th>Pull Requests</th>
                <th>Added</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {repositories.map((repo) => (
                <tr key={repo.id} data-testid={`repo-row-${repo.id}`}>
                  <td>
                    <Link
                      to={`/repositories/${repo.id}`}
                      style={{ fontWeight: 700, color: "var(--primary)" }}
                    >
                      {repo.full_name}
                    </Link>
                  </td>
                  <td className="mono">{repo.github_repo_id}</td>
                  <td>
                    <span className="badge badge-info">{repo.default_branch}</span>
                  </td>
                  <td>
                    <span className={`badge ${repo.is_active ? "badge-verified" : "badge-rejected"}`}>
                      {repo.is_active ? "ACTIVE" : "INACTIVE"}
                    </span>
                  </td>
                  <td>{repo.pull_requests_count}</td>
                  <td>{formatDate(repo.created_at)}</td>
                  <td>
                    <Link
                      to={`/repositories/${repo.id}`}
                      className="tab-btn"
                      style={{ padding: "4px 10px", fontSize: "12px", background: "var(--bg-surface-elevated)", borderRadius: "var(--radius-sm)" }}
                    >
                      View Details
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
