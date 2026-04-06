/**
 * Custom React hook for debounced similarity search with threshold.
 * Triggers search when threshold changes and manages loading/error states.
 * Optimized for <200ms UI rendering latency with memoization.
 */
import { useEffect, useState, useRef, useMemo } from 'react';
import { searchSimilarPhotos } from '../api';
import { SimilarPhotosGroup } from '../components/SimilarPhotosGrid';

export interface UseSimilaritySearchResult {
  groups: SimilarPhotosGroup[];
  loading: boolean;
  error: string | null;
}

/**
 * Hook to manage debounced similarity search with threshold parameter.
 * Debounces search requests to avoid excessive API calls during rapid threshold changes.
 * Default debounce is 100ms to meet <100ms search completion requirement.
 * @param jobId - Job identifier to search
 * @param threshold - Similarity threshold (0-1)
 * @param debounceMs - Debounce delay in milliseconds (default: 100ms)
 * @returns Object with groups, loading state, and error
 */
export function useSimilaritySearch(
  jobId: string,
  threshold: number,
  debounceMs: number = 100,
  refreshKey: number = 0
): UseSimilaritySearchResult {
  const [groups, setGroups] = useState<SimilarPhotosGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const debounceTimer = useRef<NodeJS.Timeout | null>(null);
  const previousSearchRef = useRef<{ jobId: string; threshold: number } | null>(null);

  useEffect(() => {
    if (!jobId) {
      setGroups([]);
      setLoading(false);
      return;
    }

    // Skip if search params haven't changed (avoid redundant API calls)
    // refreshKey bypass: when it changes, always re-fetch
    if (
      previousSearchRef.current &&
      previousSearchRef.current.jobId === jobId &&
      previousSearchRef.current.threshold === threshold &&
      refreshKey === (previousSearchRef as any)._refreshKey
    ) {
      return;
    }

    // Clear previous timer
    if (debounceTimer.current) {
      clearTimeout(debounceTimer.current);
    }

    // Set new debounced search (100ms debounce for <200ms UI latency)
    debounceTimer.current = setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await searchSimilarPhotos(jobId, threshold);
        setGroups(data);
        previousSearchRef.current = { jobId, threshold };
        (previousSearchRef as any)._refreshKey = refreshKey;
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
        setGroups([]);
      } finally {
        setLoading(false);
      }
    }, debounceMs);

    return () => {
      if (debounceTimer.current) {
        clearTimeout(debounceTimer.current);
      }
    };
  }, [jobId, threshold, debounceMs, refreshKey]);

  // Memoize result to prevent unnecessary re-renders of consuming components
  const result = useMemo(
    () => ({ groups, loading, error }),
    [groups, loading, error]
  );

  return result;
}
