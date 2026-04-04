/**
 * Custom React hook for debounced similarity search with threshold.
 * Triggers search when threshold changes and manages loading/error states.
 */
import { useEffect, useState, useRef } from 'react';
import { searchSimilarPhotos } from '../api';

export interface UseSimilaritySearchResult {
  groups: any[];
  loading: boolean;
  error: string | null;
}

/**
 * Hook to manage debounced similarity search with threshold parameter.
 * Debounces search requests to avoid excessive API calls during rapid threshold changes.
 * @param jobId - Job identifier to search
 * @param threshold - Similarity threshold (0-1)
 * @param debounceMs - Debounce delay in milliseconds (default: 300ms)
 * @returns Object with groups, loading state, and error
 */
export function useSimilaritySearch(
  jobId: string,
  threshold: number,
  debounceMs: number = 300
): UseSimilaritySearchResult {
  const [groups, setGroups] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const debounceTimer = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    if (!jobId) {
      setGroups([]);
      setLoading(false);
      return;
    }

    // Clear previous timer
    if (debounceTimer.current) {
      clearTimeout(debounceTimer.current);
    }

    // Set new debounced search
    debounceTimer.current = setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await searchSimilarPhotos(jobId, threshold);
        setGroups(data);
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
  }, [jobId, threshold, debounceMs]);

  return { groups, loading, error };
}
