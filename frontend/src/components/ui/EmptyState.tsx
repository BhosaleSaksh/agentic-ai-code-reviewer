import React from "react";
import { FolderGit2 } from "lucide-react";
import { cn } from "@/lib/utils/cn";

export interface EmptyStateProps {
  title?: string;
  description?: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  title = "No data found",
  description = "No items match your current criteria.",
  icon,
  action,
  className,
}) => {
  return (
    <div
      className={cn("state-container", className)}
      data-testid="empty-state"
    >
      <div className="state-icon empty">
        {icon || <FolderGit2 size={32} />}
      </div>
      <h4 className="state-title">{title}</h4>
      <p className="state-desc">{description}</p>
      {action && <div style={{ marginTop: "16px" }}>{action}</div>}
    </div>
  );
};
