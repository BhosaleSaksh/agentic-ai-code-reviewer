import { apiClient } from "@/lib/api/client";
import type { PullRequestRead, RepositoryRead } from "@/types/api";

export async function fetchRepositories(
  limit = 100,
  offset = 0,
): Promise<RepositoryRead[]> {
  return apiClient<RepositoryRead[]>(
    `/repositories?limit=${limit}&offset=${offset}`,
  );
}

export async function fetchRepositoryById(
  id: string,
): Promise<RepositoryRead> {
  return apiClient<RepositoryRead>(`/repositories/${id}`);
}

export async function fetchRepositoryPullRequests(
  repositoryId: string,
  state?: string,
  limit = 100,
  offset = 0,
): Promise<PullRequestRead[]> {
  const query = new URLSearchParams({
    limit: limit.toString(),
    offset: offset.toString(),
  });
  if (state) query.append("state", state);

  return apiClient<PullRequestRead[]>(
    `/repositories/${repositoryId}/pull-requests?${query.toString()}`,
  );
}
