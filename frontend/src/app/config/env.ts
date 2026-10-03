/**
 * Application environment configuration.
 *
 * Exposes ONLY non-sensitive client configuration.
 * NEVER put private keys, installation tokens, or database credentials here.
 */

export const env = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL || "/api/v1",
  appName: "Agentic AI Code Reviewer",
  appVersion: "v0.6.0",
} as const;
