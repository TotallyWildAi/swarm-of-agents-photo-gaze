import React, { useEffect, useState } from 'react';
import { fetchHealth, connectProgressWebSocket, ProgressUpdate, fetchPreferences, savePreferences, fetchThreshold, saveThreshold, UserPreferences } from './api';
import FolderPathSelector from './components/FolderPathSelector';
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
  const [username, setUsername] = useState<string>(() => localStorage.getItem('username') || 'default_user');
  const [preferences, setPreferences] = useState<UserPreferences | null>(null);
  const [threshold, setThreshold] = useState<number>(() => parseFloat(localStorage.getItem('threshold') || '0.5'));
  const [preferencesLoading, setPreferencesLoading] = useState(false);
  const [selectedFolders, setSelectedFolders] = useState<string[]>(() => {
    const stored = localStorage.getItem('selectedFolders');
    return stored ? JSON.parse(stored) : [];
  });

  // Load preferences and threshold on mount and when username changes
  useEffect(() => {
    const loadSessionData = async () => {
      setPreferencesLoading(true);
      try {
        const prefs = await fetchPreferences(username);
        setPreferences(prefs);
        setThreshold(prefs.threshold_setting);
        localStorage.setItem('threshold', prefs.threshold_setting.toString());
      } catch (err) {
        console.error('Failed to load preferences:', err);
        // Create default preferences if not found
        const defaultPrefs: Omit<UserPreferences, 'id'> = {
          username,
          email: `${username}@example.com`,
          preferred_embedding_model: 'clip-vit-base-patch32',
          enable_auto_processing: true,
          threshold_setting: 0.5,
        };
        try {
          const saved = await savePreferences(defaultPrefs);
          setPreferences(saved);
          setThreshold(saved.threshold_setting);
          localStorage.setItem('threshold', saved.threshold_setting.toString());
        } catch (saveErr) {
          console.error('Failed to create default preferences:', saveErr);
        }
      } finally {
        setPreferencesLoading(false);
      }
    };

    loadSessionData();
  }, [username]);

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

  const handleThresholdChange = async (newThreshold: number) => {
    setThreshold(newThreshold);
    localStorage.setItem('threshold', newThreshold.toString());
    try {
      await saveThreshold(username, newThreshold);
    } catch (err) {
      console.error('Failed to save threshold:', err);
    }
  };

  const handleUsernameChange = (newUsername: string) => {
    setUsername(newUsername);
    localStorage.setItem('username', newUsername);
  };

  const handleFolderSelect = (folders: string[]) => {
    setSelectedFolders(folders);
    localStorage.setItem('selectedFolders', JSON.stringify(folders));
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
        
        <div className="folder-selector-container">
          <FolderPathSelector onFoldersSelected={handleFolderSelect} selectedFolders={selectedFolders} />
        </div>
        
        <div className="session-container">
          <h2>Session Management</h2>
          <div className="session-input">
            <label>Username: </label>
            <input
              type="text"
              value={username}
              onChange={(e) => handleUsernameChange(e.target.value)}
              placeholder="Enter username"
            />
          </div>
          {preferencesLoading && <p>Loading preferences...</p>}
          {preferences && (
            <div className="preferences-display">
              <p>Email: <strong>{preferences.email}</strong></p>
              <p>Embedding Model: <strong>{preferences.preferred_embedding_model}</strong></p>
              <p>Auto Processing: <strong>{preferences.enable_auto_processing ? 'Enabled' : 'Disabled'}</strong></p>
              <div className="threshold-control">
                <label>Threshold Setting: </label>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.01"
                  value={threshold}
                  onChange={(e) => handleThresholdChange(parseFloat(e.target.value))}
                />
                <span>{threshold.toFixed(2)}</span>
              </div>
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
