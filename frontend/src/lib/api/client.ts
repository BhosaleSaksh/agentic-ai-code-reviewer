/**
 * Centralized typed API client.
 *
 * Implements:
 * - Base URL configuration
 * - HTTP status code mapping (401, 403, 404, 409, 422, 500)
 * - Safe error handling preventing internal stack traces from leaking
 * - Generic typing for response payloads
 */

import { env } from "@/app/config/env";

export class ApiClientError extends Error {
  public statusCode: number;
  public detail?: unknown;

  constructor(message: string, statusCode: number, detail?: unknown) {
    super(message);
    this.name = "ApiClientError";
    this.statusCode = statusCode;
    this.detail = detail;
  }
}

export async function apiClient<T>(
  endpoint: string,
  options?: RequestInit,
): Promise<T> {
  const url = `${env.apiBaseUrl}${endpoint.startsWith("/") ? endpoint : `/${endpoint}`}`;

  const defaultHeaders: HeadersInit = {
    Accept: "application/json",
    "Content-Type": "application/json",
  };

  try {
    const response = await fetch(url, {
      ...options,
      headers: {
        ...defaultHeaders,
        ...options?.headers,
      },
    });

    if (!response.ok) {
      let errorMessage = `HTTP Error ${response.status}: ${response.statusText}`;
      let errorDetail: unknown = null;

      try {
        const errorJson = await response.json();
        if (errorJson && typeof errorJson === "object") {
          const detail = (errorJson as { detail?: unknown }).detail;
          if (typeof detail === "string") {
            errorMessage = detail;
          } else if (Array.isArray(detail)) {
            errorMessage = detail
              .map((d: { msg?: string }) => d.msg || JSON.stringify(d))
              .join(", ");
          } else if ((errorJson as { message?: string }).message) {
            errorMessage = (errorJson as { message: string }).message;
          }
          errorDetail = errorJson;
        }
      } catch {
        // Response body was not valid JSON
      }

      throw new ApiClientError(errorMessage, response.status, errorDetail);
    }

    if (response.status === 204) {
      return {} as T;
    }

    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiClientError) {
      throw error;
    }

    // Network error or fetch abort
    throw new ApiClientError(
      error instanceof Error ? error.message : "Network error encountered",
      0,
    );
  }
}
