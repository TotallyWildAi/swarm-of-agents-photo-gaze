/**
 * Unit tests for useSimilaritySearch hook.
 * Tests debounced search triggering and threshold change handling.
 */
import { renderHook, waitFor } from '@testing-library/react';
import { useSimilaritySearch } from './useSimilaritySearch';
import * as api from '../api';

jest.mock('../api');

describe('useSimilaritySearch Hook', () => {
  const mockGroups = [
    {
      group_id: 'group_1',
      reference_photo: {
        photo_id: 1,
        filename: 'ref1.jpg',
        path: '/photos/ref1.jpg',
        quality_score: 0.95,
      },
      similar_photos: [
        {
          photo_id: 2,
          filename: 'sim1.jpg',
          path: '/photos/sim1.jpg',
          similarity_score: 0.92,
          quality_score: 0.88,
        },
      ],
    },
  ];

  beforeEach(() => {
    jest.clearAllMocks();
    (api.searchSimilarPhotos as jest.Mock).mockResolvedValue(mockGroups);
  });

  test('returns empty groups when jobId is empty', () => {
    const { result } = renderHook(() => useSimilaritySearch('', 0.5));
    expect(result.current.groups).toEqual([]);
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
  });

  test('triggers search when threshold changes', async () => {
    const { rerender } = renderHook(
      ({ jobId, threshold }) => useSimilaritySearch(jobId, threshold),
      { initialProps: { jobId: 'test_job', threshold: 0.5 } }
    );

    await waitFor(() => {
      expect(api.searchSimilarPhotos).toHaveBeenCalledWith('test_job', 0.5);
    });

    jest.clearAllMocks();
    (api.searchSimilarPhotos as jest.Mock).mockResolvedValue(mockGroups);

    rerender({ jobId: 'test_job', threshold: 0.75 });

    await waitFor(() => {
      expect(api.searchSimilarPhotos).toHaveBeenCalledWith('test_job', 0.75);
    });
  });

  test('debounces search requests', async () => {
    const { rerender } = renderHook(
      ({ jobId, threshold }) => useSimilaritySearch(jobId, threshold, 100),
      { initialProps: { jobId: 'test_job', threshold: 0.5 } }
    );

    rerender({ jobId: 'test_job', threshold: 0.6 });
    rerender({ jobId: 'test_job', threshold: 0.7 });
    rerender({ jobId: 'test_job', threshold: 0.75 });

    await waitFor(() => {
      expect(api.searchSimilarPhotos).toHaveBeenCalledTimes(1);
      expect(api.searchSimilarPhotos).toHaveBeenCalledWith('test_job', 0.75);
    });
  });

  test('sets loading state during search', async () => {
    (api.searchSimilarPhotos as jest.Mock).mockImplementation(
      () => new Promise(resolve => setTimeout(() => resolve(mockGroups), 50))
    );

    const { result } = renderHook(() => useSimilaritySearch('test_job', 0.5));

    expect(result.current.loading).toBe(true);

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });
  });

  test('updates groups on successful search', async () => {
    const { result } = renderHook(() => useSimilaritySearch('test_job', 0.5));

    await waitFor(() => {
      expect(result.current.groups).toEqual(mockGroups);
    });
  });

  test('sets error state on search failure', async () => {
    (api.searchSimilarPhotos as jest.Mock).mockRejectedValue(
      new Error('Network error')
    );

    const { result } = renderHook(() => useSimilaritySearch('test_job', 0.5));

    await waitFor(() => {
      expect(result.current.error).toBe('Network error');
      expect(result.current.groups).toEqual([]);
    });
  });

  test('clears error on successful search after failure', async () => {
    (api.searchSimilarPhotos as jest.Mock).mockRejectedValueOnce(
      new Error('Network error')
    );

    const { result, rerender } = renderHook(
      ({ jobId, threshold }) => useSimilaritySearch(jobId, threshold),
      { initialProps: { jobId: 'test_job', threshold: 0.5 } }
    );

    await waitFor(() => {
      expect(result.current.error).toBe('Network error');
    });

    jest.clearAllMocks();
    (api.searchSimilarPhotos as jest.Mock).mockResolvedValue(mockGroups);

    rerender({ jobId: 'test_job', threshold: 0.75 });

    await waitFor(() => {
      expect(result.current.error).toBeNull();
      expect(result.current.groups).toEqual(mockGroups);
    });
  });

  test('cleans up debounce timer on unmount', async () => {
    const { unmount } = renderHook(() => useSimilaritySearch('test_job', 0.5, 1000));

    unmount();

    jest.advanceTimersByTime(1000);
    expect(api.searchSimilarPhotos).not.toHaveBeenCalled();
  });
});
