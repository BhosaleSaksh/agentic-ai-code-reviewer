import React from "react";
import { MessageSquare, ThumbsUp, ThumbsDown, User, CheckCircle } from "lucide-react";
import { formatDate } from "@/lib/utils/formatters";
import type { FeedbackResponse } from "@/types/api";

export interface FeedbackCardProps {
  feedback: FeedbackResponse;
}

export const FeedbackCard: React.FC<FeedbackCardProps> = ({ feedback }) => {
  const getFeedbackIcon = (type: string) => {
    switch (type) {
      case "REACTION_POSITIVE":
        return <ThumbsUp size={16} style={{ color: "#10b981" }} />;
      case "REACTION_NEGATIVE":
        return <ThumbsDown size={16} style={{ color: "#ef4444" }} />;
      case "FINDING_ACCEPTED":
        return <CheckCircle size={16} style={{ color: "#10b981" }} />;
      default:
        return <MessageSquare size={16} style={{ color: "var(--primary)" }} />;
    }
  };

  return (
    <div
      className="finding-item"
      data-testid={`feedback-item-${feedback.id}`}
      style={{ padding: "16px" }}
    >
      <div className="finding-header" style={{ marginBottom: "6px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          {getFeedbackIcon(feedback.feedback_type)}
          <span style={{ fontWeight: 700, fontSize: "14px" }}>
            {feedback.feedback_type.replace(/_/g, " ")}
          </span>
          <span className="badge badge-info">{feedback.feedback_source}</span>
        </div>

        <span style={{ fontSize: "12px", color: "var(--text-muted)" }}>
          {formatDate(feedback.created_at)}
        </span>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "12px", color: "var(--text-secondary)", marginBottom: "8px" }}>
        <User size={13} />
        <span>{feedback.reviewer_username || "Unknown Reviewer"}</span>
        <span>• PR #{feedback.pr_number}</span>
        {feedback.github_comment_id && (
          <span>• Comment #{feedback.github_comment_id}</span>
        )}
      </div>

      {feedback.comment_body && (
        <p style={{ fontSize: "13px", color: "var(--text-primary)", background: "var(--bg-app)", padding: "10px", borderRadius: "var(--radius-sm)" }}>
          "{feedback.comment_body}"
        </p>
      )}

      {feedback.extra_metadata && Object.keys(feedback.extra_metadata).length > 0 && (
        <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "6px", fontFamily: "JetBrains Mono" }}>
          Metadata: {JSON.stringify(feedback.extra_metadata)}
        </div>
      )}
    </div>
  );
};
