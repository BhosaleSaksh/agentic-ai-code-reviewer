import { apiClient } from "@/lib/api/client";
import type { FeedbackResponse } from "@/types/api";

export async function fetchFeedbackList(params?: {
  repositoryId?: number;
  prNumber?: number;
  findingId?: string;
  reviewRunId?: string;
  feedbackType?: string;
  limit?: number;
  offset?: number;
}): Promise<FeedbackResponse[]> {
  const query = new URLSearchParams();
  if (params?.repositoryId)
    query.append("repository_id", params.repositoryId.toString());
  if (params?.prNumber)
    query.append("pr_number", params.prNumber.toString());
  if (params?.findingId) query.append("finding_id", params.findingId);
  if (params?.reviewRunId) query.append("review_run_id", params.reviewRunId);
  if (params?.feedbackType) query.append("feedback_type", params.feedbackType);
  if (params?.limit) query.append("limit", params.limit.toString());
  if (params?.offset) query.append("offset", params.offset.toString());

  const queryString = query.toString();
  return apiClient<FeedbackResponse[]>(
    `/feedback${queryString ? `?${queryString}` : ""}`,
  );
}

export async function fetchFeedbackById(
  id: string,
): Promise<FeedbackResponse> {
  return apiClient<FeedbackResponse>(`/feedback/${id}`);
}
