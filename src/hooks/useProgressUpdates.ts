/**
 * Custom React hook for managing WebSocket progress updates.
 * Handles connection lifecycle and progress state management.
 */
import { useEffect, useState, useCallback } from 'react';
import { connectProgressWebSocket, ProgressUpdate } from '../api';

export interface UseProgressUpdatesResult {
  progress: ProgressUpdate | null;
  isConnected: boolean;
  error: string | null;
}

/**
 * Hook to manage WebSocket connection and progress updates for a job.
 * @param jobId - Job identifier to track
 * @returns Object with progress data, connection status, and error state
 */
export function useProgressUpdates(jobId: string): UseProgressUpdatesResult {
  const [progress, setProgress] = useState<ProgressUpdate | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) {
      setProgress(null);
      setIsConnected(false);
      return;
    }

    const disconnect = connectProgressWebSocket(
      jobId,
      (data) => {
        setProgress(data);
        setIsConnected(true);
        setError(null);
        
        // Disconnect if job is no longer found
        if (data.status === 'not_found') {
          setIsConnected(false);
        }
      },
      (err) => {
        setError(err);
        setIsConnected(false);
      }
    );

    return () => {
      disconnect();
      setIsConnected(false);
    };
  }, [jobId]);

  return { progress, isConnected, error };
}
