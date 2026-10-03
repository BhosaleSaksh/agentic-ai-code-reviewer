import React from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils/cn";

export interface LoadingStateProps {
  title?: string;
  description?: string;
  className?: string;
}

export const LoadingState: React.FC<LoadingStateProps> = ({
  title = "Loading data...",
  description = "Fetching data from backend review services",
  className,
}) => {
  return (
    <div
      className={cn("state-container", className)}
      data-testid="loading-state"
    >
      <div className="state-icon loading">
        <Loader2 size={32} />
      </div>
      <h4 className="state-title">{title}</h4>
      <p className="state-desc">{description}</p>
    </div>
  );
};
