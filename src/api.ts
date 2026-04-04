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

export interface UserPreferences {
  id: number;
  username: string;
  email: string;
  preferred_embedding_model: string;
  enable_auto_processing: boolean;
  threshold_setting: number;
}

export interface ThresholdResponse {
  threshold_setting: number;
}

export interface FolderValidationResponse {
  valid: boolean;
  error?: string;
  path: string;
  photo_count?: number;
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

/**
 * Fetch user preferences from backend.
 * @param username - Username to fetch preferences for
 * @returns Promise resolving to user preferences object
 * @throws Error if request fails
 */
export async function fetchPreferences(username: string): Promise<UserPreferences> {
  const response = await fetch(`${API_BASE_URL}/preferences/${username}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch preferences: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Save user preferences to backend.
 * @param preferences - User preferences object to save
 * @returns Promise resolving to saved preferences
 * @throws Error if request fails
 */
export async function savePreferences(preferences: Omit<UserPreferences, 'id'>): Promise<UserPreferences> {
  const response = await fetch(`${API_BASE_URL}/preferences`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(preferences),
  });
  if (!response.ok) {
    throw new Error(`Failed to save preferences: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Fetch threshold setting for user.
 * @param username - Username to fetch threshold for
 * @returns Promise resolving to threshold response
 * @throws Error if request fails
 */
export async function fetchThreshold(username: string): Promise<ThresholdResponse> {
  const response = await fetch(`${API_BASE_URL}/threshold/${username}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch threshold: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Save threshold setting for user.
 * @param username - Username to save threshold for
 * @param threshold - Threshold value (0-1)
 * @returns Promise resolving to threshold response
 * @throws Error if request fails
 */
export async function saveThreshold(username: string, threshold: number): Promise<ThresholdResponse> {
  const response = await fetch(`${API_BASE_URL}/threshold/${username}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ threshold_setting: threshold }),
  });
  if (!response.ok) {
    throw new Error(`Failed to save threshold: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Validate folder path and check if it contains photos.
 * @param folderPath - Folder path to validate
 * @returns Promise resolving to validation response with photo count
 * @throws Error if request fails
 */
export async function validateFolderPath(folderPath: string): Promise<FolderValidationResponse> {
  const response = await fetch(`${API_BASE_URL}/validate-folder`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ folder_path: folderPath }),
  });
  if (!response.ok) {
    const errorData = await response.json();
    throw new Error(errorData.error || `Failed to validate folder: ${response.statusText}`);
  }
  return response.json();
}
