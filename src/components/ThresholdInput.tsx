import React, { useEffect, useState } from 'react';
import { fetchThresholdExamples, ThresholdExample } from '../api';
import './ThresholdInput.css';

interface ThresholdInputProps {
  value: number;
  onChange: (value: number) => void;
  jobId: string;
}

/**
 * ThresholdInput component allows users to set similarity threshold (0-1)
 * and displays 5 pre-computed example thresholds with sample match results.
 * Helps users understand the impact of different threshold values.
 */
function ThresholdInput({ value, onChange, jobId }: ThresholdInputProps) {
  const [examples, setExamples] = useState<ThresholdExample[]>([]);
  const [examplesLoading, setExamplesLoading] = useState(false);
  const [examplesError, setExamplesError] = useState<string | null>(null);

  // Fetch pre-computed threshold examples when jobId changes
  useEffect(() => {
    if (!jobId) {
      setExamples([]);
      return;
    }

    const loadExamples = async () => {
      setExamplesLoading(true);
      setExamplesError(null);
      try {
        const data = await fetchThresholdExamples(jobId);
        setExamples(data);
      } catch (err) {
        setExamplesError(err instanceof Error ? err.message : 'Failed to load examples');
        setExamples([]);
      } finally {
        setExamplesLoading(false);
      }
    };

    loadExamples();
  }, [jobId]);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newValue = parseFloat(e.target.value);
    if (!isNaN(newValue) && newValue >= 0 && newValue <= 1) {
      onChange(newValue);
    }
  };

  const handleNumberInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newValue = parseFloat(e.target.value);
    if (!isNaN(newValue)) {
      // Clamp value to 0-1 range
      const clampedValue = Math.max(0, Math.min(1, newValue));
      onChange(clampedValue);
    }
  };

  return (
    <div className="threshold-input-container">
      <div className="threshold-control">
        <label htmlFor="threshold-range">Similarity Threshold: </label>
        <input
          id="threshold-range"
          type="range"
          min="0"
          max="1"
          step="0.01"
          value={value}
          onChange={handleInputChange}
          className="threshold-range"
        />
        <input
          id="threshold-number"
          type="number"
          min="0"
          max="1"
          step="0.01"
          value={value.toFixed(2)}
          onChange={handleNumberInputChange}
          className="threshold-number"
        />
      </div>

      <div className="threshold-examples">
        <h3>Example Thresholds</h3>
        {examplesLoading && <p className="loading">Loading examples...</p>}
        {examplesError && <p className="error">Error: {examplesError}</p>}
        {examples.length === 0 && !examplesLoading && !examplesError && (
          <p className="no-examples">No examples available. Process a job to see threshold examples.</p>
        )}
        {examples.length > 0 && (
          <div className="examples-list">
            {examples.map((example) => (
              <div
                key={example.id}
                className={`example-item ${example.threshold === value ? 'active' : ''}`}
              >
                <div className="example-header">
                  <span className="example-threshold">{example.threshold.toFixed(2)}</span>
                  <span className="example-matches">{example.match_count} matches</span>
                </div>
                {example.sample_matches.length > 0 && (
                  <div className="sample-matches">
                    <p className="sample-label">Sample matches:</p>
                    <ul>
                      {example.sample_matches.slice(0, 3).map((match, idx) => (
                        <li key={idx}>
                          <span className="filename">{match.filename}</span>
                          <span className="score">{(match.similarity_score * 100).toFixed(1)}%</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default ThresholdInput;
