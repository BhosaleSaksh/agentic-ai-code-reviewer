import { apiClient } from "@/lib/api/client";
import type {
  EvidenceModel,
  FeedbackResponse,
  PublicationResult,
  ReviewFinding,
  ReviewRunRead,
} from "@/types/api";

export async function fetchReviewRuns(params?: {
  pullRequestId?: string;
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<ReviewRunRead[]> {
  const query = new URLSearchParams();
  if (params?.pullRequestId) query.append("pull_request_id", params.pullRequestId);
  if (params?.status) query.append("status", params.status);
  if (params?.limit) query.append("limit", params.limit.toString());
  if (params?.offset) query.append("offset", params.offset.toString());

  const queryString = query.toString();
  return apiClient<ReviewRunRead[]>(
    `/reviews${queryString ? `?${queryString}` : ""}`,
  );
}

export async function fetchReviewRunById(
  id: string,
): Promise<ReviewRunRead> {
  return apiClient<ReviewRunRead>(`/reviews/${id}`);
}

export async function fetchReviewRunFindings(
  runId: string,
  params?: {
    verificationStatus?: string;
    severity?: string;
    issueType?: string;
    limit?: number;
    offset?: number;
  },
): Promise<ReviewFinding[]> {
  const query = new URLSearchParams();
  if (params?.verificationStatus)
    query.append("verification_status", params.verificationStatus);
  if (params?.severity) query.append("severity", params.severity);
  if (params?.issueType) query.append("issue_type", params.issueType);
  if (params?.limit) query.append("limit", params.limit.toString());
  if (params?.offset) query.append("offset", params.offset.toString());

  const queryString = query.toString();
  return apiClient<ReviewFinding[]>(
    `/reviews/${runId}/findings${queryString ? `?${queryString}` : ""}`,
  );
}

export async function fetchReviewRunEvidence(
  runId: string,
): Promise<EvidenceModel[]> {
  return apiClient<EvidenceModel[]>(`/reviews/${runId}/evidence`);
}

export async function fetchReviewRunPublications(
  runId: string,
): Promise<PublicationResult[]> {
  return apiClient<PublicationResult[]>(`/reviews/${runId}/publications`);
}

export async function fetchReviewRunFeedback(
  runId: string,
): Promise<FeedbackResponse[]> {
  return apiClient<FeedbackResponse[]>(`/reviews/${runId}/feedback`);
}

export async function publishReviewRun(
  runId: string,
): Promise<ReviewRunRead> {
  return apiClient<ReviewRunRead>(`/reviews/${runId}/publish`, {
    method: "POST",
  });
}

export async function resetReviewRun(
  runId: string,
): Promise<ReviewRunRead> {
  return apiClient<ReviewRunRead>(`/reviews/${runId}/reset`, {
    method: "POST",
  });
}

