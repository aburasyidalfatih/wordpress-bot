import { useCallback, useEffect, useRef, useState } from 'react';
import { apiFetch, isAbortError } from '@/lib/api';
import type { HistoryItem, QueueItem } from '@/lib/types';

const POLL_START_MS = 3000;
const POLL_MAX_MS = 15000;

/**
 * Queue and posting history of a website. Polls while an item is being posted
 * or a history entry is being regenerated (with exponential backoff).
 */
export function useQueueData(siteId: number | null) {
  const [items, setItems] = useState<QueueItem[]>([]);
  const [historyItems, setHistoryItems] = useState<HistoryItem[]>([]);
  const [regeneratingIds, setRegeneratingIds] = useState<Record<number, boolean>>({});
  // The site whose queue finished loading, and whether a visible (non-silent)
  // reload is in progress. Together they derive `loading`.
  const [loadedSiteId, setLoadedSiteId] = useState<number | null>(null);
  const [reloading, setReloading] = useState(false);
  const pollingDelayRef = useRef(POLL_START_MS);

  // Track the current site and the in-flight request so a late response for a
  // previously selected site never overwrites the current view.
  const siteIdRef = useRef(siteId);
  const loadControllerRef = useRef<AbortController | null>(null);
  useEffect(() => { siteIdRef.current = siteId; }, [siteId]);
  useEffect(() => () => loadControllerRef.current?.abort(), []);

  const requestQueue = useCallback(() => {
    // A newer load always supersedes the previous one (polling or manual).
    loadControllerRef.current?.abort();
    if (!siteId) {
      loadControllerRef.current = null;
      return;
    }
    const controller = new AbortController();
    loadControllerRef.current = controller;
    const isStale = () => controller.signal.aborted || siteIdRef.current !== siteId;

    apiFetch(`/api/queue?site_id=${siteId}&t=${Date.now()}`, { signal: controller.signal })
      .then(res => {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(d => {
        if (isStale()) return;
        if (d.success) {
          setItems(d.queue || []);
          setHistoryItems(d.history || []);
        } else if (import.meta.env.DEV) {
          console.error('Queue API failed:', d.error);
        }
      })
      .catch(e => {
        if (isAbortError(e) || isStale()) return;
        if (import.meta.env.DEV) console.error('Failed to load queue/history:', e);
      })
      .finally(() => {
        // Only the latest request may clear the spinner; a superseded request
        // leaves it to the one that replaced it.
        if (loadControllerRef.current === controller) {
          loadControllerRef.current = null;
          setLoadedSiteId(siteId);
          setReloading(false);
        }
      });
  }, [siteId]);

  useEffect(() => {
    requestQueue();
  }, [requestQueue]);

  /** Reloads the queue; unless `silent`, the page shows its spinner meanwhile. */
  const loadQueue = useCallback((silent = false) => {
    if (!silent) setReloading(true);
    requestQueue();
  }, [requestQueue]);

  useEffect(() => {
    const hasPosting = items.some(i => i.status === 'posting');
    const hasRegenerating = Object.values(regeneratingIds).some(Boolean);
    if (!hasPosting && !hasRegenerating) {
      // Reset the delay when nothing is in progress.
      pollingDelayRef.current = POLL_START_MS;
      return;
    }
    const timeoutId = setTimeout(() => {
      loadQueue(true);
      pollingDelayRef.current = Math.min(pollingDelayRef.current * 1.5, POLL_MAX_MS);
    }, pollingDelayRef.current);
    return () => clearTimeout(timeoutId);
  }, [items, regeneratingIds, loadQueue]);

  return {
    items,
    setItems,
    historyItems,
    regeneratingIds,
    setRegeneratingIds,
    loading: siteId !== null && (loadedSiteId !== siteId || reloading),
    loadQueue,
    siteIdRef,
  };
}
