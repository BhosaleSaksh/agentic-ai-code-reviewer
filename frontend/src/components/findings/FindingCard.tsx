import React, { useState } from "react";
import { SeverityBadge } from "@/components/ui/SeverityBadge";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { EvidenceCard } from "@/components/evidence/EvidenceCard";
import type { ReviewFinding } from "@/types/api";
import { ChevronDown, ChevronUp, Layers, CheckCircle2, XCircle, Send } from "lucide-react";

export interface FindingCardProps {
  finding: ReviewFinding;
  defaultExpanded?: boolean;
}

export const FindingCard: React.FC<FindingCardProps> = ({
  finding,
  defaultExpanded = false,
}) => {
  const [expanded, setExpanded] = useState(defaultExpanded);

  const isVerified = finding.verification_status === "VERIFIED";
  const isRejected =
    finding.verification_status === "REJECTED" ||
    finding.verification_status === "SUPPRESSED_FALSE_POSITIVE" ||
    finding.verification_status === "DROPPED_LOW_CONFIDENCE";

  return (
    <article
      className="finding-item"
      data-testid={`finding-card-${finding.id}`}
      aria-labelledby={`finding-title-${finding.id}`}
    >
      <div className="finding-header">
        <div className="finding-title-row">
          <SeverityBadge severity={finding.severity} />
          <h4 id={`finding-title-${finding.id}`} className="finding-title">
            {finding.title}
          </h4>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          {/* Verification Status */}
          <StatusBadge status={finding.verification_status} type="verification" />

          {/* Publication Status Guarantee Display */}
          {isVerified ? (
            <span
              className="badge badge-published"
              title="Verified by Critic; eligible for GitHub publication"
              data-testid="publication-eligibility-badge"
            >
              <Send size={11} style={{ marginRight: "3px" }} />
              {finding.publish_status === "PUBLISHED" ? "PUBLISHED" : "ELIGIBLE TO PUBLISH"}
            </span>
          ) : (
            <span
              className="badge badge-info"
              title="Only verified findings are eligible for GitHub publication"
              data-testid="publication-ineligible-badge"
            >
              NOT PUBLISHABLE
            </span>
          )}

          <button
            onClick={() => setExpanded(!expanded)}
            className="tab-btn"
            style={{ padding: "4px 8px", fontSize: "12px" }}
            aria-expanded={expanded}
            aria-label={expanded ? "Collapse details" : "Expand details"}
          >
            {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </button>
        </div>
      </div>

      <div className="finding-location">
        {finding.file_path}:{finding.line_number} ({finding.side}) • {finding.issue_type}
        {finding.agent_name && <span> • Origin: {finding.agent_name}</span>}
      </div>

      <p className="finding-explanation">{finding.explanation}</p>

      <div className="finding-recommendation">
        <strong>Recommendation:</strong> {finding.recommendation}
      </div>

      {expanded && (
        <div style={{ marginTop: "16px", borderTop: "1px solid var(--border-subtle)", paddingTop: "14px" }}>
          {/* Critic Verification Notes */}
          <div style={{ marginBottom: "14px" }}>
            <h5 style={{ fontSize: "13px", fontWeight: 700, marginBottom: "4px", display: "flex", alignItems: "center", gap: "6px" }}>
              {isVerified ? (
                <>
                  <CheckCircle2 size={15} style={{ color: "var(--status-verified-text)" }} />
                  <span>Critic Verification Passed</span>
                </>
              ) : isRejected ? (
                <>
                  <XCircle size={15} style={{ color: "var(--status-rejected-text)" }} />
                  <span>Critic Rejection Note</span>
                </>
              ) : (
                <span>Verification State: {finding.verification_status}</span>
              )}
            </h5>

            {finding.critic_notes && (
              <p style={{ fontSize: "12px", color: "var(--text-secondary)" }}>
                {finding.critic_notes}
              </p>
            )}

            {finding.rejection_reason && (
              <p style={{ fontSize: "12px", color: "var(--status-rejected-text)", fontStyle: "italic" }}>
                Reason: {finding.rejection_reason}
              </p>
            )}

            <div style={{ fontSize: "12px", color: "var(--text-muted)", marginTop: "4px" }}>
              Confidence Score: {(finding.confidence_score * 100).toFixed(1)}%
              {finding.github_comment_id && ` • GitHub Comment #${finding.github_comment_id}`}
            </div>
          </div>

          {/* Suggested Patch if available */}
          {finding.suggested_patch && (
            <div style={{ marginBottom: "14px" }}>
              <h5 style={{ fontSize: "12px", fontWeight: 600, color: "var(--text-muted)", marginBottom: "4px" }}>
                Suggested Patch:
              </h5>
              <pre className="code-snippet">
                <code>{finding.suggested_patch}</code>
              </pre>
            </div>
          )}

          {/* Evidence Grounding Pillar Items */}
          <div>
            <h5 style={{ fontSize: "13px", fontWeight: 700, marginBottom: "8px", display: "flex", alignItems: "center", gap: "6px" }}>
              <Layers size={14} />
              <span>Grounded Evidence ({finding.evidence?.length || 0})</span>
            </h5>

            {finding.evidence && finding.evidence.length > 0 ? (
              finding.evidence.map((ev, idx) => (
                <EvidenceCard key={`${ev.file_path}-${ev.start_line}-${idx}`} evidence={ev} />
              ))
            ) : (
              <p style={{ fontSize: "12px", color: "var(--text-muted)", fontStyle: "italic" }}>
                No explicit evidence items attached.
              </p>
            )}
          </div>
        </div>
      )}
    </article>
  );
};
