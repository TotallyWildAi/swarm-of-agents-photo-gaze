import React, { useEffect, useState } from 'react';
import { fetchHealth } from './api';
import './App.css';

interface HealthStatus {
  status: string;
}

function App() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
      </header>
    </div>
  );
}

export default App;
