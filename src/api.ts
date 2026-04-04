/**
 * API client for communicating with FastAPI backend.
 * Requests are proxied through package.json proxy configuration.
 */

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

export interface HealthResponse {
  status: string;
}

/**
 * Fetch health status from FastAPI backend.
 * @returns Promise resolving to health status object
 * @throws Error if request fails
 */
export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health`);
  if (!response.ok) {
    throw new Error(`Health check failed: ${response.statusText}`);
  }
  return response.json();
}
