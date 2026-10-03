import React from "react";
import { FileCode2, ShieldAlert, GitCommit, FileText } from "lucide-react";
import type { EvidenceModel, EvidenceType } from "@/types/api";

export interface EvidenceCardProps {
  evidence: EvidenceModel;
  className?: string;
}

export const EvidenceCard: React.FC<EvidenceCardProps> = ({ evidence }) => {
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

  return (
    <div
      className="evidence-card"
      data-testid={`evidence-item-${evidence.evidence_type.toLowerCase()}`}
    >
      <div className="evidence-header">
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          {getEvidenceIcon(evidence.evidence_type)}
          <span>{evidence.evidence_type}</span>
          {evidence.corroborating_tool && (
            <span style={{ color: "var(--primary)", fontWeight: 600 }}>
              • {evidence.corroborating_tool}
            </span>
          )}
          {evidence.rule_or_cve_id && (
            <span style={{ color: "var(--text-muted)", fontFamily: "JetBrains Mono" }}>
              [{evidence.rule_or_cve_id}]
            </span>
          )}
        </div>
        <div style={{ fontFamily: "JetBrains Mono", fontSize: "11px" }}>
          {evidence.file_path}:{evidence.start_line}–{evidence.end_line}
        </div>
      </div>

      <pre className="code-snippet">
        <code>{evidence.snippet}</code>
      </pre>
    </div>
  );
};
