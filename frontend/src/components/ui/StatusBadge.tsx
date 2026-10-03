import React from "react";
import { cn } from "@/lib/utils/cn";

export interface StatusBadgeProps {
  status: string | null | undefined;
  type?: "verification" | "publication" | "review" | "generic";
  className?: string;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({
  status,
  type = "generic",
  className,
}) => {
  const norm = (status || "UNKNOWN").toUpperCase();

  let badgeClass = "badge-info";

  if (norm === "VERIFIED" || norm === "COMPLETED" || norm === "PUBLISHED" || norm === "OPEN") {
    badgeClass = "badge-verified";
  } else if (
    norm === "REJECTED" ||
    norm === "FAILED" ||
    norm === "SUPPRESSED_FALSE_POSITIVE" ||
    norm === "DROPPED_LOW_CONFIDENCE"
  ) {
    badgeClass = "badge-rejected";
  } else if (norm === "UNVERIFIED" || norm === "PENDING" || norm === "QUEUED" || norm === "RUNNING") {
    badgeClass = "badge-unverified";
  } else if (norm === "PUBLISHED") {
    badgeClass = "badge-published";
  }

  return (
    <span
      className={cn("badge", badgeClass, className)}
      data-testid={`status-badge-${type}-${norm.toLowerCase()}`}
    >
      {status || "UNKNOWN"}
    </span>
  );
};
