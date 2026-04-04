/**
 * API client for communicating with FastAPI backend.
 * Requests are proxied through package.json proxy configuration.
 */

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';
const WS_BASE_URL = process.env.REACT_APP_WS_URL || 'ws://localhost:8000';

export interface HealthResponse {
  status: string;
}

export interface ProgressUpdate {
  job_id: string;
  status: string;
  percentage: number;
  processed_photos: number;
  total_photos: number;
  eta_seconds: number | null;
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

/**
 * Connect to WebSocket endpoint for real-time progress updates.
 * @param jobId - Job identifier to track
 * @param onMessage - Callback function for progress updates
 * @param onError - Callback function for errors
 * @returns Function to close the WebSocket connection
 */
export function connectProgressWebSocket(
  jobId: string,
  onMessage: (data: ProgressUpdate) => void,
  onError: (error: string) => void
): () => void {
  const ws = new WebSocket(`${WS_BASE_URL}/ws/progress/${jobId}`);
  
  ws.onopen = () => {
    console.log(`Connected to progress updates for job ${jobId}`);
  };
  
  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data) as ProgressUpdate;
      onMessage(data);
    } catch (err) {
      onError(`Failed to parse progress update: ${err}`);
    }
  };
  
  ws.onerror = (event) => {
    onError(`WebSocket error: ${event}`);
  };
  
  ws.onclose = () => {
    console.log(`Disconnected from progress updates for job ${jobId}`);
  };
  
  // Return cleanup function
  return () => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.close();
    }
  };
}
