import { useCallback, useEffect, useRef, useState } from 'react';
import { errorMessage } from '@/lib/api';

interface ResourceState<T> {
  key: string;
  version: number;
  data: T | null;
  error: string | null;
}

/**
 * Loads a resource identified by `key` (e.g. a URL) and reloads it whenever the
 * key changes. Pass `null` as the key to load nothing. `loading` is true until
 * the current key (and the latest reload()) has a result, so switching keys never
 * shows data that belongs to the previous key.
 */
export function useApiResource<T>(key: string | null, load: (signal: AbortSignal) => Promise<T>) {
  const [version, setVersion] = useState(0);
  const [state, setState] = useState<ResourceState<T> | null>(null);

  // Always call the latest loader without making it an effect dependency.
  const loadRef = useRef(load);
  useEffect(() => { loadRef.current = load; });

  useEffect(() => {
    if (key === null) return;
    const controller = new AbortController();
    loadRef.current(controller.signal).then(
      data => setState({ key, version, data, error: null }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        if (import.meta.env.DEV) console.error(`Failed to load ${key}:`, error);
        setState({ key, version, data: null, error: errorMessage(error, 'Gagal memuat data.') });
      },
    );
    return () => controller.abort();
  }, [key, version]);

  const reload = useCallback(() => setVersion(v => v + 1), []);
  const current = state !== null && state.key === key ? state : null;
  const loading = key !== null && current?.version !== version;

  return {
    data: current?.data ?? null,
    // A reload clears the previous error until its own result arrives.
    error: loading ? null : current?.error ?? null,
    loading,
    reload,
  };
}
