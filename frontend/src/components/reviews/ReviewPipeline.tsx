import React from "react";
import { ArrowRight, CheckCircle2, Circle, Clock } from "lucide-react";
import type { ReviewRunRead } from "@/types/api";

export interface ReviewPipelineProps {
  run: ReviewRunRead;
}

export const ReviewPipeline: React.FC<ReviewPipelineProps> = ({ run }) => {
  const isCompleted = run.status === "COMPLETED";
  const isRunning = run.status === "RUNNING";

  const steps = [
    { label: "PR Ingested", status: "completed" },
    { label: "Planner", status: isCompleted ? "completed" : isRunning ? "active" : "pending" },
    { label: "Specialists", status: isCompleted ? "completed" : isRunning ? "active" : "pending" },
    { label: "Evidence", status: isCompleted ? "completed" : "pending" },
    { label: "Critic", status: isCompleted ? "completed" : "pending" },
    {
      label: `Verified (${run.verified_findings_count})`,
      status: isCompleted ? "completed" : "pending",
    },
    {
      label: `Published (${run.published_findings_count})`,
      status: run.published_findings_count > 0 ? "completed" : isCompleted ? "completed" : "pending",
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
