import React from "react";
import { ArrowRight, CheckCircle2, Circle, Clock, XCircle } from "lucide-react";
import type { ReviewRunRead } from "@/types/api";

export interface ReviewPipelineProps {
  run: ReviewRunRead;
}

export const ReviewPipeline: React.FC<ReviewPipelineProps> = ({ run }) => {
  const normalizedStatus = (run.status || "").toUpperCase();
  const isCompleted = normalizedStatus === "COMPLETED";
  const isRunning = normalizedStatus === "RUNNING";
  const isFailed = normalizedStatus === "FAILED";

  const steps = [
    { label: "PR Ingested", status: "completed" },
    {
      label: "Planner",
      status: isCompleted || !!run.review_plan ? "completed" : isRunning ? "active" : isFailed ? "failed" : "pending",
    },
    {
      label: "Specialists",
      status:
        isCompleted || run.findings_count > 0
          ? "completed"
          : isRunning && !!run.review_plan
            ? "active"
            : isFailed && !!run.review_plan
              ? "failed"
              : "pending",
    },
    {
      label: "Evidence",
      status:
        isCompleted || run.findings_count > 0
          ? "completed"
          : isRunning && !!run.review_plan
            ? "active"
            : isFailed && !!run.review_plan
              ? "failed"
              : "pending",
    },
    {
      label: "Critic",
      status:
        isCompleted || run.verified_findings_count > 0
          ? "completed"
          : isRunning && run.findings_count > 0
            ? "active"
            : isFailed && run.findings_count > 0
              ? "failed"
              : "pending",
    },
    {
      label: `Verified (${run.verified_findings_count})`,
      status: isCompleted || run.verified_findings_count > 0 ? "completed" : isRunning ? "active" : "pending",
    },
    {
      label: `Published (${run.published_findings_count})`,
      status:
        run.published_findings_count > 0
          ? "completed"
          : isCompleted
            ? "completed"
            : isRunning && run.verified_findings_count > 0
              ? "active"
              : "pending",
    },
  ];

  return (
    <div className="pipeline-flow" data-testid="review-pipeline" aria-label="Review Pipeline Progress">
      {steps.map((step, idx) => (
        <React.Fragment key={step.label}>
          <div className={`pipeline-step ${step.status}`}>
            {step.status === "completed" ? (
              <CheckCircle2 size={14} color="#10b981" />
            ) : step.status === "active" ? (
              <Clock size={14} color="var(--primary)" />
            ) : step.status === "failed" ? (
              <XCircle size={14} color="#ef4444" />
            ) : (
              <Circle size={14} color="var(--text-muted)" />
            )}
            <span>{step.label}</span>
          </div>

          {idx < steps.length - 1 && (
            <ArrowRight size={14} className="pipeline-arrow" />
          )}
        </React.Fragment>
      ))}
    </div>
  );
};
