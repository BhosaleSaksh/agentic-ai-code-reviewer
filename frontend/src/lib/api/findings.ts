import { apiClient } from "@/lib/api/client";
import type { EvidenceModel, ReviewFinding } from "@/types/api";

export async function fetchFindings(params?: {
  reviewRunId?: string;
  verificationStatus?: string;
  severity?: string;
  issueType?: string;
  limit?: number;
  offset?: number;
}): Promise<ReviewFinding[]> {
  const query = new URLSearchParams();
  if (params?.reviewRunId) query.append("review_run_id", params.reviewRunId);
  if (params?.verificationStatus)
    query.append("verification_status", params.verificationStatus);
  if (params?.severity) query.append("severity", params.severity);
  if (params?.issueType) query.append("issue_type", params.issueType);
  if (params?.limit) query.append("limit", params.limit.toString());
  if (params?.offset) query.append("offset", params.offset.toString());

  const queryString = query.toString();
  return apiClient<ReviewFinding[]>(
    `/findings${queryString ? `?${queryString}` : ""}`,
  );
}

export async function fetchFindingById(id: string): Promise<ReviewFinding> {
  return apiClient<ReviewFinding>(`/findings/${id}`);
}

export async function fetchFindingEvidence(
  id: string,
): Promise<EvidenceModel[]> {
  return apiClient<EvidenceModel[]>(`/findings/${id}/evidence`);
}
