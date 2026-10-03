import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchFeedbackList } from "@/lib/api/feedback";
import { queryKeys } from "@/lib/query/queryKeys";
import { LoadingState } from "@/components/ui/LoadingState";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { FeedbackCard } from "@/components/feedback/FeedbackCard";
import { MessageSquareQuote, Filter } from "lucide-react";

export const FeedbackPage: React.FC = () => {
  const [feedbackTypeFilter, setFeedbackTypeFilter] = useState<string>("ALL");

  const {
    data: feedbackItems,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: queryKeys.feedback.list({
      feedbackType: feedbackTypeFilter === "ALL" ? undefined : feedbackTypeFilter,
    }),
    queryFn: () =>
      fetchFeedbackList({
        feedbackType:
          feedbackTypeFilter === "ALL" ? undefined : feedbackTypeFilter,
      }),
  });

  const feedbackTypes = [
    "ALL",
    "REACTION_POSITIVE",
    "REACTION_NEGATIVE",
    "FINDING_ACCEPTED",
    "FINDING_DISMISSED",
    "COMMENT_REPLY",
  ];

  return (
    <div>
      <div className="page-header">
        <div>
          <h2 className="page-heading">Developer Review Feedback</h2>
          <p className="page-subheading">
            Audit log of developer reactions, inline replies, and resolution signals on GitHub comments
          </p>
        </div>
      </div>

      {/* Filter Tabs */}
      <div className="card" style={{ marginBottom: "20px", padding: "14px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px", fontSize: "13px", fontWeight: 600, color: "var(--text-secondary)" }}>
          <Filter size={14} />
          <span>Filter by Feedback Type</span>
        </div>

        <div className="tab-group">
          {feedbackTypes.map((ft) => (
            <button
              key={ft}
              onClick={() => setFeedbackTypeFilter(ft)}
              className={`tab-btn ${feedbackTypeFilter === ft ? "active" : ""}`}
              style={{ fontSize: "12px", padding: "4px 10px" }}
              data-testid={`filter-feedback-${ft.toLowerCase()}`}
            >
              {ft.replace(/_/g, " ")}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <LoadingState title="Loading Feedback Events" description="Retrieving developer feedback signals..." />
      ) : error ? (
        <ErrorState
          title="Failed to Load Feedback"
          message={error instanceof Error ? error.message : "Error fetching feedback"}
          onRetry={() => refetch()}
        />
      ) : !feedbackItems || feedbackItems.length === 0 ? (
        <EmptyState
          icon={<MessageSquareQuote size={40} />}
          title="No developer feedback recorded"
          description={
            feedbackTypeFilter === "ALL"
              ? "When developers react or reply to published GitHub comments, webhook events will be recorded here."
              : `No feedback events found with type '${feedbackTypeFilter}'.`
          }
        />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
          {feedbackItems.map((item) => (
            <FeedbackCard key={item.id} feedback={item} />
          ))}
        </div>
      )}
    </div>
  );
};
