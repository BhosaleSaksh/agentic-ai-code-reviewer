import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { apiClient, ApiClientError } from "@/lib/api/client";

describe("API Client Error Handling and Sanitization", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("handles successful 200 JSON responses", async () => {
    const mockData = { total_repositories: 5, total_pull_requests: 12 };
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockData,
    });

    const result = await apiClient<typeof mockData>("/dashboard/metrics");
    expect(result).toEqual(mockData);
  });

  it("maps 404 Not Found error into ApiClientError without leaking stack traces", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
      json: async () => ({
        detail: "Finding 12345 not found",
        traceback: "Traceback (most recent call last): File /app/server.py line 42",
      }),
    });

    await expect(apiClient("/findings/12345")).rejects.toThrow(ApiClientError);

    try {
      await apiClient("/findings/12345");
    } catch (err) {
      const apiErr = err as ApiClientError;
      expect(apiErr.statusCode).toBe(404);
      expect(apiErr.message).toBe("Finding 12345 not found");
      // Verify raw backend internal paths or traceback are not the primary message
      expect(apiErr.message).not.toContain("Traceback");
    }
  });

  it("maps 422 Unprocessable Entity error detail safely", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      statusText: "Unprocessable Entity",
      json: async () => ({
        detail: [
          { loc: ["query", "limit"], msg: "ensure this value is greater than 0", type: "value_error" },
        ],
      }),
    });

    try {
      await apiClient("/reviews?limit=-1");
    } catch (err) {
      const apiErr = err as ApiClientError;
      expect(apiErr.statusCode).toBe(422);
      expect(apiErr.message).toContain("ensure this value is greater than 0");
    }
  });

  it("maps 500 Internal Server Error cleanly", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      json: async () => ({
        detail: "Database connection failed",
      }),
    });

    try {
      await apiClient("/reviews");
    } catch (err) {
      const apiErr = err as ApiClientError;
      expect(apiErr.statusCode).toBe(500);
      expect(apiErr.message).toBe("Database connection failed");
    }
  });

  it("handles non-JSON error responses gracefully", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      statusText: "Bad Gateway",
      json: async () => {
        throw new Error("Invalid JSON");
      },
    });

    try {
      await apiClient("/reviews");
    } catch (err) {
      const apiErr = err as ApiClientError;
      expect(apiErr.statusCode).toBe(502);
      expect(apiErr.message).toBe("HTTP Error 502: Bad Gateway");
    }
  });
});
