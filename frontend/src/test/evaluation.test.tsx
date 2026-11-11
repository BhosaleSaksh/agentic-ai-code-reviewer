import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { EvaluationPage } from "@/features/evaluation/EvaluationPage";

const createTestQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

const mockSummary = {
  run_id: "3b8d2539-07a3-40b5-9533-072b87debf93",
  baseline_name: "agentic_critic_full",
  execution_mode: "real_llm",
  provider: "ollama",
  model: "qwen3:4b-instruct",
  dataset_version: "1.0.0",
  timestamp: "2026-10-21T11:51:33.947175+00:00",
  git_commit_sha: "af0f0427252487b6cd0b76bba14a0d611fd67024",
  total_cases: 23,
  overall_metrics: {
    true_positives: 22,
    false_positives: 0,
    true_negatives: 0,
    false_negatives: 1,
    precision: 1.0,
    recall: 0.9565,
    f1_score: 0.9778,
    false_positive_rate: 0.0,
    false_negative_rate: 0.0435,
    defect_detection_rate: 0.9565,
    precision_ci: [0.8513, 1.0],
    recall_ci: [0.7901, 0.9923],
  },
  category_metrics: {
    BUG_LOGIC: {
      true_positives: 6,
      false_positives: 0,
      true_negatives: 0,
      false_negatives: 0,
      precision: 1.0,
      recall: 1.0,
      f1_score: 1.0,
      false_positive_rate: 0.0,
      false_negative_rate: 0.0,
      defect_detection_rate: 1.0,
    },
  },
};

const mockBaselines = [
  {
    name: "Agentic Critic (Ours)",
    key: "agentic_critic_full",
    model: "qwen3:4b-instruct",
    total_cases: 23,
    true_positives: 22,
    false_positives: 0,
    true_negatives: 0,
    false_negatives: 1,
    precision: 1.0,
    recall: 0.9565,
    f1_score: 0.9778,
    false_positive_rate: 0.0,
    defect_detection_rate: 0.9565,
  },
];

const mockCases = [
  {
    case_id: "SYNTH-BUG-001",
    category: "BUG_LOGIC",
    title: "refactor(queue): optimize batch item processing",
    description: "Processes input batch list items.",
    affected_file: "app/processors/batch_queue.py",
    classification: "TRUE_POSITIVE",
    ground_truth_count: 1,
    predicted_count: 1,
    true_positives: 1,
    false_positives: 0,
    false_negatives: 0,
    duplicates: 0,
    semantic_score: 1.0,
    line_distance: 0,
    ground_truth_defect_id: "DEFECT-BUG-001",
    match_explanation: "Matched DEFECT-BUG-001 at lines 3-4",
    matched_pairs: [],
    unmatched_predictions: [],
    unmatched_ground_truth: [],
    resource_usage: {
      latency_seconds: 0.0006,
      api_calls: 8,
      prompt_tokens: 2250,
      completion_tokens: 750,
      total_tokens: 3000,
      estimated_cost_usd: 0.0,
    },
  },
];

describe("Evaluation & Confusion Matrix Page", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the 2x2 confusion matrix and top metrics accurately", async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/evaluation/summary")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockSummary,
        });
      }
      if (url.includes("/evaluation/baselines")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockBaselines,
        });
      }
      if (url.includes("/evaluation/cases")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockCases,
        });
      }
      if (url.includes("/evaluation/live-prs")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => [],
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({}),
      });
    });

    const queryClient = createTestQueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/evaluation"]}>
          <EvaluationPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText("Evaluation Benchmark & Confusion Matrix")).toBeInTheDocument();
    });

    // Check top metric cards
    expect(screen.getAllByText("100.0%").length).toBeGreaterThan(0); // Precision
    expect(screen.getAllByText("95.7%").length).toBeGreaterThan(0); // Recall
    expect(screen.getAllByText("97.8%").length).toBeGreaterThan(0); // F1 Score

    // Check 2x2 confusion matrix cells
    expect(screen.getByTestId("cm-tp")).toBeInTheDocument();
    expect(screen.getByTestId("cm-fn")).toBeInTheDocument();
    expect(screen.getByTestId("cm-fp")).toBeInTheDocument();
    expect(screen.getByTestId("cm-tn")).toBeInTheDocument();

    // Check TP value 22 and FN value 1
    expect(screen.getByTestId("cm-tp")).toHaveTextContent("22");
    expect(screen.getByTestId("cm-fn")).toHaveTextContent("1");
    expect(screen.getByTestId("cm-fp")).toHaveTextContent("0");

    // Check comparative baseline table
    expect(screen.getByText("Comparative Baseline Analysis (Ablation Study)")).toBeInTheDocument();
    expect(screen.getByText("Agentic Critic (Ours)")).toBeInTheDocument();
  });
});
