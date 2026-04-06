import React, { useEffect, useState, useRef } from 'react';
import { fetchHealth, connectProgressWebSocket, ProgressUpdate, fetchPreferences, savePreferences, fetchThreshold, saveThreshold, UserPreferences, HealthResponse, fetchStats, triggerRescan, processPending, ProcessingStats, listFolders, addFolder, deleteFolder, scanFolder, FolderEntry } from './api';
import SimilarPhotosGrid from './components/SimilarPhotosGrid';
import './App.css';

function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
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
  const thresholdDebounceTimer = useRef<NodeJS.Timeout | null>(null);
  const [stats, setStats] = useState<ProcessingStats | null>(null);
  const [rescanStatus, setRescanStatus] = useState<string>('');
  const [folders, setFolders] = useState<FolderEntry[]>([]);
  const [newFolderPath, setNewFolderPath] = useState<string>('');
  const [folderError, setFolderError] = useState<string>('');

  const refreshFolders = async () => {
    try { setFolders(await listFolders()); } catch (e) { /* backend may be starting */ }
  };

  useEffect(() => {
    refreshFolders();
  }, []);

  const handleAddFolder = async () => {
    setFolderError('');
    const path = newFolderPath.trim();
    if (!path) return;
    try {
      await addFolder(path);
      setNewFolderPath('');
      await refreshFolders();
    } catch (e) {
      setFolderError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleDeleteFolder = async (id: number) => {
    try { await deleteFolder(id); await refreshFolders(); } catch (e) { setFolderError(String(e)); }
  };

  const handleScanFolder = async (id: number) => {
    setRescanStatus('Starting scan...');
    try {
      const res = await scanFolder(id);
      setRescanStatus(res.message + (res.job_id ? ` (job ${res.job_id.slice(0, 8)})` : ''));
      if (res.job_id) setJobId(res.job_id);
    } catch (e) {
      setRescanStatus(`Scan failed: ${e instanceof Error ? e.message : e}`);
    }
  };

  // Poll /stats every 3 seconds so progress is visible live
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const s = await fetchStats();
        if (!cancelled) setStats(s);
      } catch {
        /* ignore transient errors */
      }
    };
    poll();
    const id = setInterval(poll, 3000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const handleRescan = async () => {
    setRescanStatus('Starting rescan...');
    try {
      const res = await triggerRescan();
      setRescanStatus(res.message + (res.job_id ? ` (job ${res.job_id.slice(0, 8)})` : ''));
      if (res.job_id) setJobId(res.job_id);
    } catch (e) {
      setRescanStatus(`Rescan failed: ${e instanceof Error ? e.message : e}`);
    }
  };

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
    
    // Debounce threshold save to DB (500ms) to avoid excessive API calls
    if (thresholdDebounceTimer.current) {
      clearTimeout(thresholdDebounceTimer.current);
    }
    thresholdDebounceTimer.current = setTimeout(async () => {
      try {
        await saveThreshold(username, newThreshold);
      } catch (err) {
        console.error('Failed to save threshold:', err);
      }
    }, 500);
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
    <div className="app">
      <header className="app-header">
        <h1>Similar Photos Finder</h1>
      </header>
      <main className="app-main">
        <div className="top-panels">
          <section>
            <h3 style={{ marginTop: 0 }}>Photo Folders</h3>
            <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
              <input
                type="text"
                value={newFolderPath}
                onChange={(e) => setNewFolderPath(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleAddFolder()}
                placeholder="/Users/you/Pictures/vacation"
                style={{ flex: 1, padding: '8px 10px', fontFamily: 'monospace', fontSize: 13 }}
              />
              <button onClick={handleAddFolder} style={{ padding: '8px 14px', cursor: 'pointer' }}>Add</button>
            </div>
            {folderError && <p style={{ color: '#c00', marginTop: 0, fontSize: 13 }}>{folderError}</p>}
            {folders.length === 0 ? (
              <p style={{ color: '#888', margin: 0, fontSize: 13 }}>No folders yet.</p>
            ) : (
              <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                {folders.map((f) => (
                  <li key={f.id} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 0', borderTop: '1px solid #eee', fontSize: 13 }}>
                    <span style={{ color: f.is_accessible ? '#090' : '#c00' }}>{f.is_accessible ? '●' : '✗'}</span>
                    <code style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.path}</code>
                    <button onClick={() => handleScanFolder(f.id)} disabled={!f.is_accessible} style={{ padding: '2px 8px', cursor: f.is_accessible ? 'pointer' : 'not-allowed', fontSize: 12 }}>Scan</button>
                    <button onClick={() => handleDeleteFolder(f.id)} style={{ padding: '2px 8px', cursor: 'pointer', fontSize: 12 }}>Remove</button>
                  </li>
                ))}
              </ul>
            )}
            {rescanStatus && <p style={{ color: '#666', fontSize: 12, marginBottom: 0 }}>{rescanStatus}</p>}
          </section>

          <section>
            <h3 style={{ marginTop: 0 }}>Processing Status</h3>
            {stats ? (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8 }}>
                <Stat label="Photos" value={stats.photos} />
                <Stat label="Embeddings" value={stats.embeddings} />
                <Stat label="Completed" value={stats.completed} />
                <Stat label="Pending" value={stats.pending} />
                <Stat label="Failed" value={stats.failed} />
              </div>
            ) : (
              <p style={{ color: '#888', margin: 0 }}>Waiting for backend...</p>
            )}
            <div style={{ marginTop: 10, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <button onClick={handleRescan} style={{ padding: '6px 12px', cursor: 'pointer', fontSize: 13 }}>Rescan all</button>
              <button
                onClick={async () => {
                  setRescanStatus('Queuing...');
                  try {
                    const r = await processPending();
                    setRescanStatus(`${r.message}: ${r.queued ?? 0} queued`);
                    if (r.job_id) setJobId(r.job_id);
                  } catch (e) {
                    setRescanStatus(`Failed: ${e instanceof Error ? e.message : e}`);
                  }
                }}
                style={{ padding: '6px 12px', cursor: 'pointer', fontSize: 13 }}
              >Process pending</button>
            </div>
          </section>
        </div>

        <div className="threshold-row">
          <label htmlFor="threshold-slider">Similarity Threshold:</label>
          <input
            id="threshold-slider"
            type="range" min="0" max="1" step="0.01"
            value={threshold}
            onChange={(e) => handleThresholdChange(parseFloat(e.target.value))}
            style={{ flex: 1 }}
          />
          <span style={{ fontFamily: 'monospace', minWidth: 40 }}>{threshold.toFixed(2)}</span>
        </div>

        <SimilarPhotosGrid jobId={jobId} threshold={threshold} />
      </main>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div style={{ textAlign: 'center', padding: 8, background: '#f5f5f5', borderRadius: 4 }}>
      <div style={{ fontSize: 22, fontWeight: 600 }}>{value}</div>
      <div style={{ fontSize: 12, color: '#666' }}>{label}</div>
    </div>
  );
}

export default App;
