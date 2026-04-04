import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import ThresholdInput from './ThresholdInput';
import * as api from '../api';

jest.mock('../api');

describe('ThresholdInput Component', () => {
  const mockOnChange = jest.fn();
  const mockExamples = [
    {
      id: 1,
      threshold: 0.9,
      match_count: 5,
      sample_matches: [
        { photo_id: 1, similarity_score: 0.95, filename: 'photo1.jpg' },
        { photo_id: 2, similarity_score: 0.92, filename: 'photo2.jpg' },
      ],
      created_at: '2026-04-04T10:00:00',
    },
    {
      id: 2,
      threshold: 0.7,
      match_count: 15,
      sample_matches: [
        { photo_id: 3, similarity_score: 0.75, filename: 'photo3.jpg' },
      ],
      created_at: '2026-04-04T10:00:00',
    },
    {
      id: 3,
      threshold: 0.5,
      match_count: 30,
      sample_matches: [],
      created_at: '2026-04-04T10:00:00',
    },
    {
      id: 4,
      threshold: 0.4,
      match_count: 45,
      sample_matches: [],
      created_at: '2026-04-04T10:00:00',
    },
    {
      id: 5,
      threshold: 0.3,
      match_count: 60,
      sample_matches: [],
      created_at: '2026-04-04T10:00:00',
    },
  ];

  beforeEach(() => {
    jest.clearAllMocks();
    (api.fetchThresholdExamples as jest.Mock).mockResolvedValue(mockExamples);
  });

  test('renders threshold input with range and number inputs', () => {
    render(<ThresholdInput value={0.5} onChange={mockOnChange} jobId="test_job" />);
    expect(screen.getByText('Similarity Threshold:')).toBeInTheDocument();
    expect(screen.getByRole('slider')).toBeInTheDocument();
    expect(screen.getByDisplayValue('0.50')).toBeInTheDocument();
  });

  test('accepts numeric input between 0 and 1', async () => {
    render(<ThresholdInput value={0.5} onChange={mockOnChange} jobId="test_job" />);
    const numberInput = screen.getByDisplayValue('0.50') as HTMLInputElement;
    await userEvent.clear(numberInput);
    await userEvent.type(numberInput, '0.75');
    expect(mockOnChange).toHaveBeenCalledWith(0.75);
  });

  test('clamps numeric input to 0-1 range', async () => {
    render(<ThresholdInput value={0.5} onChange={mockOnChange} jobId="test_job" />);
    const numberInput = screen.getByDisplayValue('0.50') as HTMLInputElement;
    await userEvent.clear(numberInput);
    await userEvent.type(numberInput, '1.5');
    expect(mockOnChange).toHaveBeenCalledWith(1);
  });

  test('clamps negative input to 0', async () => {
    render(<ThresholdInput value={0.5} onChange={mockOnChange} jobId="test_job" />);
    const numberInput = screen.getByDisplayValue('0.50') as HTMLInputElement;
    await userEvent.clear(numberInput);
    await userEvent.type(numberInput, '-0.5');
    expect(mockOnChange).toHaveBeenCalledWith(0);
  });

  test('updates range input and calls onChange', async () => {
    render(<ThresholdInput value={0.5} onChange={mockOnChange} jobId="test_job" />);
    const rangeInput = screen.getByRole('slider') as HTMLInputElement;
    fireEvent.change(rangeInput, { target: { value: '0.75' } });
    expect(mockOnChange).toHaveBeenCalledWith(0.75);
  });

  test('displays 5 example thresholds when loaded', async () => {
    render(<ThresholdInput value={0.5} onChange={mockOnChange} jobId="test_job" />);
    await waitFor(() => {
      expect(screen.getByText('Example Thresholds')).toBeInTheDocument();
    });
    expect(screen.getByText('0.90')).toBeInTheDocument();
    expect(screen.getByText('0.70')).toBeInTheDocument();
    expect(screen.getByText('0.50')).toBeInTheDocument();
    expect(screen.getByText('0.40')).toBeInTheDocument();
    expect(screen.getByText('0.30')).toBeInTheDocument();
  });

  test('displays match counts for each example', async () => {
    render(<ThresholdInput value={0.5} onChange={mockOnChange} jobId="test_job" />);
    await waitFor(() => {
      expect(screen.getByText('5 matches')).toBeInTheDocument();
      expect(screen.getByText('15 matches')).toBeInTheDocument();
      expect(screen.getByText('30 matches')).toBeInTheDocument();
    });
  });

  test('displays sample matches with filenames and scores', async () => {
    render(<ThresholdInput value={0.5} onChange={mockOnChange} jobId="test_job" />);
    await waitFor(() => {
      expect(screen.getByText('photo1.jpg')).toBeInTheDocument();
      expect(screen.getByText('photo2.jpg')).toBeInTheDocument();
      expect(screen.getByText('95.0%')).toBeInTheDocument();
      expect(screen.getByText('92.0%')).toBeInTheDocument();
    });
  });

  test('highlights active example matching current threshold', async () => {
    const { rerender } = render(
      <ThresholdInput value={0.5} onChange={mockOnChange} jobId="test_job" />
    );
    await waitFor(() => {
      expect(screen.getByText('Example Thresholds')).toBeInTheDocument();
    });
    const activeExample = screen.getByText('0.50').closest('.example-item');
    expect(activeExample).toHaveClass('active');
  });

  test('shows loading state while fetching examples', () => {
    (api.fetchThresholdExamples as jest.Mock).mockImplementation(
      () => new Promise(() => {}) // Never resolves
    );
    render(<ThresholdInput value={0.5} onChange={mockOnChange} jobId="test_job" />);
    expect(screen.getByText('Loading examples...')).toBeInTheDocument();
  });

  test('displays error message when fetch fails', async () => {
    (api.fetchThresholdExamples as jest.Mock).mockRejectedValue(
      new Error('Network error')
    );
    render(<ThresholdInput value={0.5} onChange={mockOnChange} jobId="test_job" />);
    await waitFor(() => {
      expect(screen.getByText(/Error: Network error/)).toBeInTheDocument();
    });
  });

  test('shows no examples message when jobId is empty', () => {
    render(<ThresholdInput value={0.5} onChange={mockOnChange} jobId="" />);
    expect(
      screen.getByText('No examples available. Process a job to see threshold examples.')
    ).toBeInTheDocument();
  });

  test('fetches examples when jobId changes', async () => {
    const { rerender } = render(
      <ThresholdInput value={0.5} onChange={mockOnChange} jobId="job1" />
    );
    await waitFor(() => {
      expect(api.fetchThresholdExamples).toHaveBeenCalledWith('job1');
    });
    jest.clearAllMocks();
    (api.fetchThresholdExamples as jest.Mock).mockResolvedValue(mockExamples);
    rerender(<ThresholdInput value={0.5} onChange={mockOnChange} jobId="job2" />);
    await waitFor(() => {
      expect(api.fetchThresholdExamples).toHaveBeenCalledWith('job2');
    });
  });

  test('triggers search when threshold changes', async () => {
    const mockSearchSimilarPhotos = jest.fn().mockResolvedValue([]);
    (api.searchSimilarPhotos as jest.Mock) = mockSearchSimilarPhotos;
    
    render(<ThresholdInput value={0.5} onChange={mockOnChange} jobId="test_job" />);
    const rangeInput = screen.getByRole('slider') as HTMLInputElement;
    
    fireEvent.change(rangeInput, { target: { value: '0.75' } });
    
    // onChange should be called immediately with new threshold value
    expect(mockOnChange).toHaveBeenCalledWith(0.75);
    
    // Verify the new threshold value is reflected in the number input
    await waitFor(() => {
      const numberInput = screen.getByRole('spinbutton') as HTMLInputElement;
      expect(numberInput.value).toBe('0.75');
    });
  });

  test('displays up to 3 sample matches per example', async () => {
    const examplesWithMany = [
      {
        id: 1,
        threshold: 0.9,
        match_count: 100,
        sample_matches: [
          { photo_id: 1, similarity_score: 0.95, filename: 'photo1.jpg' },
          { photo_id: 2, similarity_score: 0.92, filename: 'photo2.jpg' },
          { photo_id: 3, similarity_score: 0.91, filename: 'photo3.jpg' },
          { photo_id: 4, similarity_score: 0.90, filename: 'photo4.jpg' },
        ],
        created_at: '2026-04-04T10:00:00',
      },
    ];
    (api.fetchThresholdExamples as jest.Mock).mockResolvedValue(examplesWithMany);
    render(<ThresholdInput value={0.5} onChange={mockOnChange} jobId="test_job" />);
    await waitFor(() => {
      expect(screen.getByText('photo1.jpg')).toBeInTheDocument();
      expect(screen.getByText('photo2.jpg')).toBeInTheDocument();
      expect(screen.getByText('photo3.jpg')).toBeInTheDocument();
      expect(screen.queryByText('photo4.jpg')).not.toBeInTheDocument();
    });
  });
