/**
 * Evaluation and Confusion Matrix TypeScript types.
 *
 * Models authoritative scientific benchmark evaluation metrics, 2x2 confusion matrices,
 * multi-baseline ablation results, and per-PR / case defect detection records.
 */

export interface ConfusionMatrixMetrics {
  true_positives: number;
  false_positives: number;
  true_negatives: number;
  false_negatives: number;
  precision: number;
  recall: number;
  f1_score: number;
  false_positive_rate: number;
  false_negative_rate: number;
  defect_detection_rate: number;
  precision_ci?: [number, number];
  recall_ci?: [number, number];
}

export interface CategoryMetricsMap {
  [category: string]: ConfusionMatrixMetrics;
}

export interface EvaluationSummary {
  run_id: string;
  baseline_name: string;
  execution_mode: string;
  provider: string;
  model: string;
  dataset_version: string;
  timestamp: string;
  git_commit_sha: string;
  total_cases: number;
  overall_metrics: ConfusionMatrixMetrics;
  category_metrics: CategoryMetricsMap;
}

export interface MatchedPair {
  matched: boolean;
  ground_truth_id: string;
  predicted_finding_id: string;
  file_matched: boolean;
  line_distance: number;
  category_matched: boolean;
  semantic_score: number;
  is_duplicate: boolean;
  explanation: string;
}

export interface UnmatchedItem {
  defect_id?: string;
  category?: string;
  affected_file?: string;
  line_start?: number;
  line_end?: number;
  description?: string;
  expected_severity?: string;
  [key: string]: unknown;
}

export interface ResourceUsage {
  latency_seconds: number;
  api_calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
}

export interface EvaluationCase {
  case_id: string;
  category: string;
  title: string;
  description: string;
  affected_file: string;
  classification: "TRUE_POSITIVE" | "FALSE_POSITIVE" | "FALSE_NEGATIVE" | "TRUE_NEGATIVE";
  ground_truth_count: number;
  predicted_count: number;
  true_positives: number;
  false_positives: number;
  false_negatives: number;
  duplicates: number;
  semantic_score: number;
  line_distance: number | null;
  ground_truth_defect_id: string;
  match_explanation: string;
  matched_pairs: MatchedPair[];
  unmatched_predictions: UnmatchedItem[];
  unmatched_ground_truth: UnmatchedItem[];
  resource_usage: ResourceUsage;
}

export interface BaselineComparisonItem {
  name: string;
  key: string;
  model: string;
  total_cases: number;
  true_positives: number;
  false_positives: number;
  true_negatives: number;
  false_negatives: number;
  precision: number;
  recall: number;
  f1_score: number;
  false_positive_rate: number;
  defect_detection_rate: number;
}

export interface LivePrReviewItem {
  pr_id: string;
  pr_number: number;
  title: string;
  author: string;
  state: string;
  repository_name: string;
  additions: number;
  deletions: number;
  changed_files_count: number;
  created_at: string;
  review_run_id: string | null;
  review_status: string;
  latency_seconds: number | null;
  total_findings: number;
  verified_findings: number;
  critic_rejected_findings: number;
  critic_filter_rate: number;
  published_findings: number;
}

