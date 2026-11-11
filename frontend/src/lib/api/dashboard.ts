import { apiClient } from "@/lib/api/client";
import type { DashboardMetrics } from "@/types/api";

export async function fetchDashboardMetrics(): Promise<DashboardMetrics> {
  return apiClient<DashboardMetrics>("/dashboard/metrics");
}
