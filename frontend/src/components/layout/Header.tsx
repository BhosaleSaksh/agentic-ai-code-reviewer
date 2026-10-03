import React from "react";
import { useLocation } from "react-router-dom";

export const Header: React.FC = () => {
  const location = useLocation();

  const getPageTitle = (pathname: string): string => {
    if (pathname.startsWith("/dashboard")) return "Review Observability Dashboard";
    if (pathname.startsWith("/repositories")) return "Tracked Repositories";
    if (pathname.startsWith("/pull-requests")) return "Ingested Pull Requests";
    if (pathname.startsWith("/reviews")) return "Review Pipeline Executions";
    if (pathname.startsWith("/findings")) return "Code Review Findings";
    if (pathname.startsWith("/feedback")) return "Developer Review Feedback";
    return "Agentic Code Reviewer";
  };

  return (
    <header className="header" role="banner">
      <div className="header-title-section">
        <h2 className="header-title">{getPageTitle(location.pathname)}</h2>
      </div>

      <div className="header-meta">
        <div className="system-status-indicator" title="Connected to Backend Review API">
          <span className="status-dot" />
          <span>Backend Online</span>
        </div>
      </div>
    </header>
  );
};
