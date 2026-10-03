import React from "react";
import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  GitFork,
  GitPullRequest,
  CheckCircle2,
  ShieldAlert,
  MessageSquareQuote,
  Sparkles,
} from "lucide-react";

export const Sidebar: React.FC = () => {
  return (
    <aside className="sidebar" aria-label="Sidebar Navigation">
      <div className="sidebar-header">
        <div className="sidebar-brand-icon">
          <Sparkles size={20} />
        </div>
        <div className="sidebar-brand-text">
          <h1>Agentic Reviewer</h1>
          <span>Evidence-Based AI</span>
        </div>
      </div>

      <nav className="sidebar-nav">
        <NavLink
          to="/dashboard"
          className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
          id="nav-dashboard"
        >
          <LayoutDashboard size={18} />
          <span>Dashboard</span>
        </NavLink>

        <NavLink
          to="/repositories"
          className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
          id="nav-repositories"
        >
          <GitFork size={18} />
          <span>Repositories</span>
        </NavLink>

        <NavLink
          to="/pull-requests"
          className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
          id="nav-pull-requests"
        >
          <GitPullRequest size={18} />
          <span>Pull Requests</span>
        </NavLink>

        <NavLink
          to="/reviews"
          className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
          id="nav-reviews"
        >
          <CheckCircle2 size={18} />
          <span>Review Runs</span>
        </NavLink>

        <NavLink
          to="/findings"
          className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
          id="nav-findings"
        >
          <ShieldAlert size={18} />
          <span>Findings</span>
        </NavLink>

        <NavLink
          to="/feedback"
          className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
          id="nav-feedback"
        >
          <MessageSquareQuote size={18} />
          <span>Feedback</span>
        </NavLink>
      </nav>

      <div className="sidebar-footer">
        <p>Phase 6 Review System</p>
        <p style={{ marginTop: "4px", color: "var(--text-secondary)" }}>v0.6.0-dashboard</p>
      </div>
    </aside>
  );
};
