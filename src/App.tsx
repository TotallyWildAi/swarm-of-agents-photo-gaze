import React, { useEffect, useState } from 'react';
import { fetchHealth, connectProgressWebSocket, ProgressUpdate } from './api';
import './App.css';

interface HealthStatus {
  status: string;
}

function App() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<ProgressUpdate | null>(null);
  const [jobId, setJobId] = useState<string>('test_job_001');
  const [wsConnected, setWsConnected] = useState(false);

  useEffect(() => {
    const checkHealth = async () => {
      try {
        const data = await fetchHealth();
        setHealth(data);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
        setHealth(null);
      } finally {
        setLoading(false);
      }
    };

    checkHealth();
  }, []);

  // Connect to WebSocket for progress updates when jobId changes
  useEffect(() => {
    if (!jobId) return;
    
    const disconnect = connectProgressWebSocket(
      jobId,
      (data) => {
        setProgress(data);
        setWsConnected(true);
        if (data.status === 'not_found') {
          setWsConnected(false);
        }
      },
      (err) => {
        console.error('Progress update error:', err);
        setWsConnected(false);
      }
    );
    
    return () => {
      disconnect();
      setWsConnected(false);
    };
  }, [jobId]);

  const formatETA = (seconds: number | null): string => {
    if (seconds === null || seconds === undefined) return 'Calculating...';
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const minutes = Math.round(seconds / 60);
    return `${minutes}m`;
  };

  return (
    <div className="App">
      <header className="App-header">
        <h1>Full-Stack Application</h1>
        <div className="status-container">
          {loading && <p>Loading...</p>}
          {error && <p className="error">Error: {error}</p>}
          {health && (
            <div className="health-status">
              <p>Backend Status: <strong>{health.status}</strong></p>
            </div>
          )}
        </div>
        
        <div className="progress-container">
          <h2>Job Progress Monitor</h2>
          <div className="job-input">
            <label>Job ID: </label>
            <input
              type="text"
              value={jobId}
              onChange={(e) => setJobId(e.target.value)}
              placeholder="Enter job ID"
            />
            <span className={`ws-status ${wsConnected ? 'connected' : 'disconnected'}`}>
              {wsConnected ? '● Connected' : '● Disconnected'}
            </span>
          </div>
          
          {progress && progress.status !== 'not_found' && (
            <div className="progress-display">
              <div className="progress-info">
                <p>Status: <strong>{progress.status}</strong></p>
                <p>Progress: <strong>{progress.percentage}%</strong></p>
                <p>Photos: {progress.processed_photos} / {progress.total_photos}</p>
                <p>ETA: <strong>{formatETA(progress.eta_seconds)}</strong></p>
              </div>
              <div className="progress-bar">
                <div
                  className="progress-fill"
                  style={{ width: `${progress.percentage}%` }}
                />
              </div>
            </div>
          )}
          
          {progress && progress.status === 'not_found' && (
            <p className="info">Job not found or not started</p>
          )}
        </div>
      </header>
    </div>
  );
}

export default App;
