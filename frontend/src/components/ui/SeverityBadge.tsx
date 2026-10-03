import React from "react";
import { cn } from "@/lib/utils/cn";
import type { Severity } from "@/types/api";

export interface SeverityBadgeProps {
  severity: Severity | string;
  className?: string;
}

export const SeverityBadge: React.FC<SeverityBadgeProps> = ({
  severity,
  className,
}) => {
  const norm = (severity || "INFO").toLowerCase();
  return (
    <span
      className={cn("badge", `badge-${norm}`, className)}
      data-testid={`severity-badge-${norm}`}
    >
      {severity}
    </span>
  );
};
