import React, { useState } from 'react';
import { ProgressUpdate, pauseJob, resumeJob, cancelJob } from '../api';
import './ProgressBar.css';

interface ProgressBarProps {
  progress: ProgressUpdate | null;
  jobId: string;
}

/**
 * ProgressBar component displays real-time job progress with controls.
 * Shows percentage completion, estimated time remaining, and pause/resume/cancel buttons.
 */
function ProgressBar({ progress, jobId }: ProgressBarProps) {
  const [isPaused, setIsPaused] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const formatETA = (seconds: number | null): string => {
    if (seconds === null || seconds === undefined) return 'Calculating...';
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const minutes = Math.round(seconds / 60);
    return `${minutes}m`;
  };

  const handlePause = async () => {
    setIsLoading(true);
    setError(null);
    try {
      await pauseJob(jobId);
      setIsPaused(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to pause job');
    } finally {
      setIsLoading(false);
    }
  };

  const handleResume = async () => {
    setIsLoading(true);
    setError(null);
    try {
      await resumeJob(jobId);
      setIsPaused(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to resume job');
    } finally {
      setIsLoading(false);
    }
  };

  const handleCancel = async () => {
    setIsLoading(true);
    setError(null);
    try {
      await cancelJob(jobId);
      setIsPaused(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to cancel job');
    } finally {
      setIsLoading(false);
    }
  };

  if (!progress) {
    return <div className="progress-bar-container">No progress data available</div>;
  }

  if (progress.status === 'not_found') {
    return <div className="progress-bar-container">Job not found</div>;
  }

  const percentage = progress.percentage || 0;
  const eta = formatETA(progress.eta_seconds);

  return (
    <div className="progress-bar-container">
      {error && <div className="progress-error">{error}</div>}
      <div className="progress-info">
        <span className="progress-percentage">{percentage}%</span>
        <span className="progress-eta">ETA: {eta}</span>
      </div>
      <div className="progress-bar-wrapper">
        <div className="progress-bar" style={{ width: `${percentage}%` }} />
      </div>
      <div className="progress-details">
        <p>Processed: {progress.processed_photos} / {progress.total_photos} photos</p>
        <p>Status: {progress.status}</p>
      </div>
      <div className="progress-controls">
        {!isPaused ? (
          <button
            onClick={handlePause}
            disabled={isLoading || percentage === 100}
            className="btn-pause"
          >
            Pause
          </button>
        ) : (
          <button
            onClick={handleResume}
            disabled={isLoading}
            className="btn-resume"
          >
            Resume
          </button>
        )}
        <button
          onClick={handleCancel}
          disabled={isLoading || percentage === 100}
          className="btn-cancel"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

export default ProgressBar;
