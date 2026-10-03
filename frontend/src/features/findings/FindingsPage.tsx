import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchFindings } from "@/lib/api/findings";
import { queryKeys } from "@/lib/query/queryKeys";
import { LoadingState } from "@/components/ui/LoadingState";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { FindingCard } from "@/components/findings/FindingCard";
import { Layers, Filter } from "lucide-react";

export const FindingsPage: React.FC = () => {
  const [statusFilter, setStatusFilter] = useState<string>("ALL");
  const [severityFilter, setSeverityFilter] = useState<string>("ALL");
  const [issueTypeFilter, setIssueTypeFilter] = useState<string>("ALL");

  const {
    data: findings,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: queryKeys.findings.list({
      verificationStatus: statusFilter === "ALL" ? undefined : statusFilter,
      severity: severityFilter === "ALL" ? undefined : severityFilter,
      issueType: issueTypeFilter === "ALL" ? undefined : issueTypeFilter,
    }),
    queryFn: () =>
      fetchFindings({
        verificationStatus: statusFilter === "ALL" ? undefined : statusFilter,
        severity: severityFilter === "ALL" ? undefined : severityFilter,
        issueType: issueTypeFilter === "ALL" ? undefined : issueTypeFilter,
      }),
  });

  const statuses = [
    "ALL",
    "VERIFIED",
    "REJECTED",
    "UNVERIFIED",
    "SUPPRESSED_FALSE_POSITIVE",
    "DROPPED_LOW_CONFIDENCE",
  ];

  const severities = ["ALL", "HIGH", "MEDIUM", "LOW"];

  const issueTypes = [
    "ALL",
    "SECURITY",
    "BUG_LOGIC",
    "ERROR_HANDLING",
    "PERFORMANCE",
    "MAINTAINABILITY",
    "TEST_ADEQUACY",
  ];

  return (
    <div>
      <div className="page-header">
        <div>
          <h2 className="page-heading">Review Findings Explorer</h2>
          <p className="page-subheading">
            Grounded code review findings verified by Critic and audited against repository diffs
          </p>
        </div>
      </div>

      {/* Filter Controls Card */}
      <div className="card" style={{ marginBottom: "20px", padding: "16px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "12px", color: "var(--text-secondary)", fontSize: "13px", fontWeight: 600 }}>
          <Filter size={15} />
          <span>Filter Findings</span>
        </div>

        {/* Verification Status Filter */}
        <div style={{ marginBottom: "12px" }}>
          <div style={{ fontSize: "11px", color: "var(--text-muted)", textTransform: "uppercase", marginBottom: "6px", fontWeight: 700 }}>
            Verification Status
          </div>
          <div className="tab-group">
            {statuses.map((s) => (
              <button
                key={s}
                onClick={() => setStatusFilter(s)}
                className={`tab-btn ${statusFilter === s ? "active" : ""}`}
                style={{ fontSize: "11px", padding: "4px 8px" }}
                data-testid={`filter-status-${s.toLowerCase()}`}
              >
                {s.replace(/_/g, " ")}
              </button>
            ))}
          </div>
        </div>

        {/* Severity & Issue Type Filter Row */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: "24px" }}>
          <div>
            <div style={{ fontSize: "11px", color: "var(--text-muted)", textTransform: "uppercase", marginBottom: "6px", fontWeight: 700 }}>
              Severity
            </div>
            <div className="tab-group">
              {severities.map((sev) => (
                <button
                  key={sev}
                  onClick={() => setSeverityFilter(sev)}
                  className={`tab-btn ${severityFilter === sev ? "active" : ""}`}
                  style={{ fontSize: "11px", padding: "4px 8px" }}
                  data-testid={`filter-sev-${sev.toLowerCase()}`}
                >
                  {sev}
                </button>
              ))}
            </div>
          </div>

          <div>
            <div style={{ fontSize: "11px", color: "var(--text-muted)", textTransform: "uppercase", marginBottom: "6px", fontWeight: 700 }}>
              Issue Type
            </div>
            <div className="tab-group">
              {issueTypes.map((it) => (
                <button
                  key={it}
                  onClick={() => setIssueTypeFilter(it)}
                  className={`tab-btn ${issueTypeFilter === it ? "active" : ""}`}
                  style={{ fontSize: "11px", padding: "4px 8px" }}
                  data-testid={`filter-type-${it.toLowerCase()}`}
                >
                  {it.replace(/_/g, " ")}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Findings List */}
      {isLoading ? (
        <LoadingState title="Loading Findings" description="Querying review findings..." />
      ) : error ? (
        <ErrorState
          title="Failed to Load Findings"
          message={error instanceof Error ? error.message : "Error fetching findings"}
          onRetry={() => refetch()}
        />
      ) : !findings || findings.length === 0 ? (
        <EmptyState
          icon={<Layers size={40} />}
          title="No findings match current filters"
          description="Try broadening your filter criteria or execute a new review run."
        />
      ) : (
        <div className="findings-list">
          {findings.map((f) => (
            <FindingCard key={f.id} finding={f} defaultExpanded={false} />
          ))}
        </div>
      )}
    </div>
  );
};
