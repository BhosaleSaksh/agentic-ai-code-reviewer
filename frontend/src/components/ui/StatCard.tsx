import React from "react";
import { cn } from "@/lib/utils/cn";

export interface StatCardProps {
  label: string;
  value: string | number;
  description?: string;
  icon?: React.ReactNode;
  className?: string;
  testId?: string;
}

export const StatCard: React.FC<StatCardProps> = ({
  label,
  value,
  description,
  icon,
  className,
  testId,
}) => {
  return (
    <div
      className={cn("stat-card", className)}
      data-testid={testId || `stat-card-${label.toLowerCase().replace(/\s+/g, "-")}`}
    >
      <div className="stat-header">
        <span className="stat-label">{label}</span>
        {icon && <div className="stat-icon">{icon}</div>}
      </div>
      <div className="stat-value">{value}</div>
      {description && <div className="stat-desc">{description}</div>}
    </div>
  );
};
