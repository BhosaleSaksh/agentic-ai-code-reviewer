import { apiClient } from "@/lib/api/client";
import type { PullRequestRead, ReviewRunRead } from "@/types/api";

export async function fetchPullRequests(params?: {
  repositoryId?: string;
  state?: string;
  limit?: number;
  offset?: number;
}): Promise<PullRequestRead[]> {
  const query = new URLSearchParams();
  if (params?.repositoryId) query.append("repository_id", params.repositoryId);
  if (params?.state) query.append("state", params.state);
  if (params?.limit) query.append("limit", params.limit.toString());
  if (params?.offset) query.append("offset", params.offset.toString());

  const queryString = query.toString();
  return apiClient<PullRequestRead[]>(
    `/pull-requests${queryString ? `?${queryString}` : ""}`,
  );
}

export async function fetchPullRequestById(
  id: string,
): Promise<PullRequestRead> {
  return apiClient<PullRequestRead>(`/pull-requests/${id}`);
}

export async function fetchPullRequestReviews(
  id: string,
  status?: string,
): Promise<ReviewRunRead[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return apiClient<ReviewRunRead[]>(`/pull-requests/${id}/reviews${query}`);
}
