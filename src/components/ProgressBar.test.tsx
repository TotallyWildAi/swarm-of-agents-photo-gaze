import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import ProgressBar from './ProgressBar';
import * as api from '../api';

jest.mock('../api');

describe('ProgressBar Component', () => {
  const mockProgress = {
    percentage: 50,
    eta_seconds: 120,
    status: 'processing',
    processed_photos: 50,
    total_photos: 100,
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('renders progress bar with percentage and ETA', () => {
    render(<ProgressBar progress={mockProgress} jobId="test_job_001" />);
    expect(screen.getByText('50%')).toBeInTheDocument();
    expect(screen.getByText(/ETA: 2m/)).toBeInTheDocument();
  });

  test('displays processed and total photos', () => {
    render(<ProgressBar progress={mockProgress} jobId="test_job_001" />);
    expect(screen.getByText('Processed: 50 / 100 photos')).toBeInTheDocument();
  });

  test('displays status', () => {
    render(<ProgressBar progress={mockProgress} jobId="test_job_001" />);
    expect(screen.getByText('Status: processing')).toBeInTheDocument();
  });

  test('calls pauseJob when Pause button clicked', async () => {
    (api.pauseJob as jest.Mock).mockResolvedValue({ success: true, message: 'Job paused' });
    render(<ProgressBar progress={mockProgress} jobId="test_job_001" />);
    const pauseBtn = screen.getByRole('button', { name: /Pause/i });
    fireEvent.click(pauseBtn);
    await waitFor(() => {
      expect(api.pauseJob).toHaveBeenCalledWith('test_job_001');
    });
  });

  test('shows Resume button after pause', async () => {
    (api.pauseJob as jest.Mock).mockResolvedValue({ success: true, message: 'Job paused' });
    render(<ProgressBar progress={mockProgress} jobId="test_job_001" />);
    const pauseBtn = screen.getByRole('button', { name: /Pause/i });
    fireEvent.click(pauseBtn);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Resume/i })).toBeInTheDocument();
    });
  });

  test('calls resumeJob when Resume button clicked', async () => {
    (api.pauseJob as jest.Mock).mockResolvedValue({ success: true, message: 'Job paused' });
    (api.resumeJob as jest.Mock).mockResolvedValue({ success: true, message: 'Job resumed' });
    render(<ProgressBar progress={mockProgress} jobId="test_job_001" />);
    const pauseBtn = screen.getByRole('button', { name: /Pause/i });
    fireEvent.click(pauseBtn);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Resume/i })).toBeInTheDocument();
    });
    const resumeBtn = screen.getByRole('button', { name: /Resume/i });
    fireEvent.click(resumeBtn);
    await waitFor(() => {
      expect(api.resumeJob).toHaveBeenCalledWith('test_job_001');
    });
  });

  test('calls cancelJob when Cancel button clicked', async () => {
    (api.cancelJob as jest.Mock).mockResolvedValue({ success: true, message: 'Job cancelled' });
    render(<ProgressBar progress={mockProgress} jobId="test_job_001" />);
    const cancelBtn = screen.getByRole('button', { name: /Cancel/i });
    fireEvent.click(cancelBtn);
    await waitFor(() => {
      expect(api.cancelJob).toHaveBeenCalledWith('test_job_001');
    });
  });

  test('displays error message when pause fails', async () => {
    (api.pauseJob as jest.Mock).mockRejectedValue(new Error('Pause failed'));
    render(<ProgressBar progress={mockProgress} jobId="test_job_001" />);
    const pauseBtn = screen.getByRole('button', { name: /Pause/i });
    fireEvent.click(pauseBtn);
    await waitFor(() => {
      expect(screen.getByText('Pause failed')).toBeInTheDocument();
    });
  });

  test('disables Pause button when progress is 100%', () => {
    const completedProgress = { ...mockProgress, percentage: 100 };
    render(<ProgressBar progress={completedProgress} jobId="test_job_001" />);
    const pauseBtn = screen.getByRole('button', { name: /Pause/i }) as HTMLButtonElement;
    expect(pauseBtn.disabled).toBe(true);
  });

  test('displays "No progress data available" when progress is null', () => {
    render(<ProgressBar progress={null} jobId="test_job_001" />);
    expect(screen.getByText('No progress data available')).toBeInTheDocument();
  });

  test('displays "Job not found" when status is not_found', () => {
    const notFoundProgress = { ...mockProgress, status: 'not_found' };
    render(<ProgressBar progress={notFoundProgress} jobId="test_job_001" />);
    expect(screen.getByText('Job not found')).toBeInTheDocument();
  });

  test('formats ETA correctly for seconds', () => {
    const shortEtaProgress = { ...mockProgress, eta_seconds: 45 };
    render(<ProgressBar progress={shortEtaProgress} jobId="test_job_001" />);
    expect(screen.getByText(/ETA: 45s/)).toBeInTheDocument();
  });

  test('formats ETA correctly for minutes', () => {
    const longEtaProgress = { ...mockProgress, eta_seconds: 300 };
    render(<ProgressBar progress={longEtaProgress} jobId="test_job_001" />);
    expect(screen.getByText(/ETA: 5m/)).toBeInTheDocument();
  });

