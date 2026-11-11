/**
 * API methods for Evaluation Benchmark and Confusion Matrix data.
 */

import { apiClient } from "@/lib/api/client";
import type {
  EvaluationSummary,
  EvaluationCase,
  BaselineComparisonItem,
  LivePrReviewItem,
} from "@/types/evaluation";

export async function fetchEvaluationSummary(): Promise<EvaluationSummary> {
  return apiClient<EvaluationSummary>("/evaluation/summary");
}

export async function fetchEvaluationCases(
  category?: string,
): Promise<EvaluationCase[]> {
  const params = new URLSearchParams();
  if (category && category !== "ALL") {
    params.append("category", category);
  }
  const query = params.toString() ? `?${params.toString()}` : "";
  return apiClient<EvaluationCase[]>(`/evaluation/cases${query}`);
}

export async function fetchBaselineComparison(): Promise<BaselineComparisonItem[]> {
  return apiClient<BaselineComparisonItem[]>("/evaluation/baselines");
}

export async function fetchLivePrReviews(): Promise<LivePrReviewItem[]> {
  return apiClient<LivePrReviewItem[]>("/evaluation/live-prs");
}

