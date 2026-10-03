import React from "react";
import { AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils/cn";

export interface ErrorStateProps {
  title?: string;
  message?: string;
  onRetry?: () => void;
  className?: string;
}

export const ErrorState: React.FC<ErrorStateProps> = ({
  title = "Failed to load data",
  message = "An error occurred while connecting to backend services.",
  onRetry,
  className,
}) => {
  return (
    <div
      className={cn("state-container", className)}
      data-testid="error-state"
    >
      <div className="state-icon error">
        <AlertCircle size={32} />
      </div>
      <h4 className="state-title">{title}</h4>
      <p className="state-desc">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="nav-link active"
          style={{ marginTop: "16px", cursor: "pointer" }}
        >
          Try Again
        </button>
      )}
    </div>
  );
};
