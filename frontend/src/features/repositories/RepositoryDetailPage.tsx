import React from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { fetchRepositoryById, fetchRepositoryPullRequests } from "@/lib/api/repositories";
import { queryKeys } from "@/lib/query/queryKeys";
import { LoadingState } from "@/components/ui/LoadingState";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { formatDate, truncateSha } from "@/lib/utils/formatters";

export const RepositoryDetailPage: React.FC = () => {
  const { repositoryId } = useParams<{ repositoryId: string }>();

  const {
    data: repo,
    isLoading: isLoadingRepo,
    error: repoError,
  } = useQuery({
    queryKey: queryKeys.repositories.detail(repositoryId || ""),
    queryFn: () => fetchRepositoryById(repositoryId || ""),
    enabled: !!repositoryId,
  });

  const {
    data: pullRequests,
    isLoading: isLoadingPRs,
  } = useQuery({
    queryKey: queryKeys.repositories.pullRequests(repositoryId || ""),
    queryFn: () => fetchRepositoryPullRequests(repositoryId || ""),
    enabled: !!repositoryId,
  });

  if (isLoadingRepo) {
    return <LoadingState title="Loading Repository" description="Fetching repository metadata..." />;
  }

  if (repoError || !repo) {
    return (
      <ErrorState
        title="Repository Not Found"
        message={repoError instanceof Error ? repoError.message : "The requested repository could not be found."}
      />
    );
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <div style={{ marginBottom: "6px" }}>
            <Link to="/repositories" style={{ color: "var(--text-muted)", fontSize: "13px" }}>
              ← Back to Repositories
            </Link>
          </div>
          <h2 className="page-heading">{repo.full_name}</h2>
          <p className="page-subheading">
            Default Branch: {repo.default_branch} • GitHub Repo ID: {repo.github_repo_id}
          </p>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <h3 className="card-title">Pull Requests ({pullRequests?.length || 0})</h3>
        </div>

        {isLoadingPRs ? (
          <LoadingState description="Loading pull requests..." />
        ) : !pullRequests || pullRequests.length === 0 ? (
          <EmptyState
            title="No pull requests found"
            description="No pull requests have been ingested yet for this repository."
          />
        ) : (
          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>PR #</th>
                  <th>Title</th>
                  <th>Author</th>
                  <th>State</th>
                  <th>Commit</th>
                  <th>Changes</th>
                  <th>Latest Review</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {pullRequests.map((pr) => (
                  <tr key={pr.id}>
                    <td>
                      <Link
                        to={`/pull-requests/${pr.id}`}
                        style={{ color: "var(--primary)", fontWeight: 700 }}
                      >
                        #{pr.pr_number}
                      </Link>
                    </td>
                    <td>{pr.title}</td>
                    <td>{pr.author}</td>
                    <td>
                      <StatusBadge status={pr.state} />
                    </td>
                    <td className="mono">{truncateSha(pr.head_sha)}</td>
                    <td>
                      <span style={{ color: "#10b981", marginRight: "6px" }}>+{pr.additions}</span>
                      <span style={{ color: "#ef4444" }}>-{pr.deletions}</span>
                    </td>
                    <td>
                      {pr.latest_review_run_id ? (
                        <Link
                          to={`/reviews/${pr.latest_review_run_id}`}
                          className="tab-btn"
                          style={{ padding: "3px 8px", fontSize: "11px" }}
                        >
                          <StatusBadge status={pr.latest_review_run_status} type="review" />
                        </Link>
                      ) : (
                        <span style={{ color: "var(--text-muted)", fontSize: "12px" }}>None</span>
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
    </div>
  );
};
