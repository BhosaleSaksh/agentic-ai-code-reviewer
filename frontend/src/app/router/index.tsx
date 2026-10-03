import { createBrowserRouter, Navigate } from "react-router-dom";
import { Layout } from "@/components/layout/Layout";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { RepositoriesPage } from "@/features/repositories/RepositoriesPage";
import { RepositoryDetailPage } from "@/features/repositories/RepositoryDetailPage";
import { PullRequestsPage } from "@/features/pull-requests/PullRequestsPage";
import { PullRequestDetailPage } from "@/features/pull-requests/PullRequestDetailPage";
import { ReviewRunsPage } from "@/features/review-runs/ReviewRunsPage";
import { ReviewRunDetailPage } from "@/features/review-runs/ReviewRunDetailPage";
import { FindingsPage } from "@/features/findings/FindingsPage";
import { FeedbackPage } from "@/features/feedback/FeedbackPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      {
        index: true,
        element: <Navigate to="/dashboard" replace />,
      },
      {
        path: "dashboard",
        element: <DashboardPage />,
      },
      {
        path: "repositories",
        element: <RepositoriesPage />,
      },
      {
        path: "repositories/:repositoryId",
        element: <RepositoryDetailPage />,
      },
      {
        path: "pull-requests",
        element: <PullRequestsPage />,
      },
      {
        path: "pull-requests/:pullRequestId",
        element: <PullRequestDetailPage />,
      },
      {
        path: "reviews",
        element: <ReviewRunsPage />,
      },
      {
        path: "reviews/:reviewRunId",
        element: <ReviewRunDetailPage />,
      },
      {
        path: "findings",
        element: <FindingsPage />,
      },
      {
        path: "feedback",
        element: <FeedbackPage />,
      },
      {
        path: "*",
        element: <Navigate to="/dashboard" replace />,
      },
    ],
  },
]);
