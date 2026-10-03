import React from "react";
import { FileCode2, ShieldAlert, GitCommit, FileText } from "lucide-react";
import type { EvidenceModel, EvidenceType } from "@/types/api";
import { truncateSha } from "@/lib/utils/formatters";

export interface EvidenceCardProps {
  evidence: EvidenceModel;
  commitSha?: string | null;
  className?: string;
}

export const EvidenceCard: React.FC<EvidenceCardProps> = ({
  evidence,
  commitSha,
  className,
}) => {
  const getEvidenceIcon = (type: EvidenceType) => {
    switch (type) {
      case "DIFF_HUNK":
        return <GitCommit size={14} />;
      case "STATIC_ANALYSIS":
        return <ShieldAlert size={14} />;
      case "DEPENDENCY":
        return <FileCode2 size={14} />;
      case "AST_CONTEXT":
        return <FileText size={14} />;
      default:
        return <FileCode2 size={14} />;
    }
  };

  const metadata = (evidence.metadata || evidence.extra_metadata || {}) as Record<string, unknown>;
  const snippetCandidate =
    evidence.snippet && evidence.snippet.trim().length > 0
      ? evidence.snippet
      : evidence.content_snippet;
  const rawSnippet = snippetCandidate || "";
  const hasSnippet = rawSnippet.trim().length > 0;

  const toolName =
    evidence.corroborating_tool ||
    (metadata.analyzer as string) ||
    (evidence.evidence_type === "DIFF_HUNK"
      ? "Git Diff"
      : evidence.evidence_type === "AST_CONTEXT"
        ? "AST Analyzer"
        : "—");

  const rawRuleOrCve =
    evidence.rule_or_cve_id ||
    (metadata.rule_id as string) ||
    (metadata.test_id as string) ||
    null;

  const isCve = rawRuleOrCve ? /^(CVE|GHSA|PYSEC)-/i.test(rawRuleOrCve) : false;
  const cveId = isCve
    ? rawRuleOrCve
    : (metadata.cve_id as string) || (metadata.vuln_id as string) || null;

  const ruleDisplay = !isCve ? rawRuleOrCve : null;

  const commit = commitSha || (metadata.commit_sha as string) || null;

  const contextDescription =
    (metadata.issue_text as string) ||
    (metadata.message as string) ||
    (metadata.description as string) ||
    null;

  return (
    <div
      className={`evidence-card ${className || ""}`}
      data-testid={`evidence-item-${evidence.evidence_type.toLowerCase()}`}
    >
      <div className="evidence-header">
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          {getEvidenceIcon(evidence.evidence_type)}
          <span style={{ fontWeight: 600, color: "var(--text-muted)" }}>
            Grounding Evidence
          </span>
          {evidence.id && (
            <span style={{ color: "var(--text-muted)", fontFamily: "JetBrains Mono", fontSize: "11px" }}>
              #{evidence.id.slice(0, 8)}
            </span>
          )}
        </div>
      </div>

      {/* Structured Details Grid */}
      <div className="evidence-meta-grid">
        <div className="evidence-meta-item">
          <span className="evidence-meta-label">Evidence Type</span>
          <span className="evidence-meta-value">{evidence.evidence_type}</span>
        </div>

        <div className="evidence-meta-item">
          <span className="evidence-meta-label">Source / Tool</span>
          <span className="evidence-meta-value">{toolName}</span>
        </div>

        {ruleDisplay && (
          <div className="evidence-meta-item">
            <span className="evidence-meta-label">Rule</span>
            <span className="evidence-meta-value mono">{ruleDisplay}</span>
          </div>
        )}

        {cveId && (
          <div className="evidence-meta-item">
            <span className="evidence-meta-label">CVE</span>
            <span className="evidence-meta-value mono" style={{ color: "var(--warning)" }}>
              {cveId}
            </span>
          </div>
        )}

        <div className="evidence-meta-item">
          <span className="evidence-meta-label">Location</span>
          <span className="evidence-meta-value mono">
            {evidence.file_path}:{evidence.start_line}–{evidence.end_line}
          </span>
        </div>

        {commit && (
          <div className="evidence-meta-item">
            <span className="evidence-meta-label">Commit</span>
            <span className="evidence-meta-value mono">{truncateSha(commit)}</span>
          </div>
        )}
      </div>

      {contextDescription && (
        <div className="evidence-context-note">
          {contextDescription}
        </div>
      )}

      {/* Code Snippet Area */}
      <div className="evidence-snippet-container">
        <div className="evidence-snippet-label">Code Snippet</div>
        {hasSnippet ? (
          <pre className="code-snippet">
            <code>{rawSnippet}</code>
          </pre>
        ) : (
          <div className="code-snippet-unavailable">
            Code snippet unavailable
          </div>
        )}
      </div>
    </div>
  );
};
