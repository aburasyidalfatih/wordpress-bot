import { useState, useEffect, useRef, useCallback } from 'react';
import type { ReactNode } from 'react';
import { apiFetch, isAbortError } from '@/lib/api';
import type { WordPressSite } from '@/lib/types';
import { SiteContext } from './siteContextValue';

export function SiteProvider({ children }: { children: ReactNode }) {
  const [sites, setSites] = useState<WordPressSite[]>([]);
  const [selectedSiteId, setSelectedSiteId] = useState<number | null>(() => {
    const saved = localStorage.getItem('selectedSiteId');
    return saved ? parseInt(saved, 10) : null;
  });
  const [loading, setLoading] = useState(true);

  const selectedSiteIdRef = useRef(selectedSiteId);
  useEffect(() => { selectedSiteIdRef.current = selectedSiteId; }, [selectedSiteId]);

  // Only the most recent fetchSites call may update state, so a stale request
  // (e.g. the unauthenticated mount fetch) can't overwrite a post-login result.
  const requestIdRef = useRef(0);

  const fetchSites = useCallback((signal?: AbortSignal): Promise<void> => {
    const requestId = ++requestIdRef.current;
    const isLatest = () => requestId === requestIdRef.current;
    // Users may be authenticated via the localStorage token or only via the
    // httpOnly auth_token cookie, so always try. A 401 here (e.g. on public
    // pages) is expected and must not redirect to /login.
    return apiFetch('/api/sites', { signal, redirectOnUnauthorized: false })
      .then(async response => {
        if (!isLatest()) return;
        if (response.status === 401) {
          setSites([]);
          return;
        }
        if (!response.ok) throw new Error('HTTP ' + response.status);
        const data = await response.json();
        if (!isLatest() || !data.success || !data.sites) return;
        const nextSites: WordPressSite[] = data.sites;
        setSites(nextSites);

        const currentSelectedId = selectedSiteIdRef.current;
        // Select the first site when nothing is selected or the selected site is gone.
        if (!currentSelectedId && nextSites.length > 0) {
          setSelectedSiteId(nextSites[0].id);
        } else if (currentSelectedId && !nextSites.some(s => s.id === currentSelectedId)) {
          setSelectedSiteId(nextSites.length > 0 ? nextSites[0].id : null);
        }
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) return;
        if (import.meta.env.DEV) console.error('Failed to fetch sites:', error);
      })
      .finally(() => {
        if (isLatest()) setLoading(false);
      });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    fetchSites(controller.signal);
    return () => controller.abort();
  }, [fetchSites]);

  useEffect(() => {
    if (selectedSiteId !== null) {
      localStorage.setItem('selectedSiteId', selectedSiteId.toString());
    } else {
      localStorage.removeItem('selectedSiteId');
    }
  }, [selectedSiteId]);

  const selectedSite = sites.find(s => s.id === selectedSiteId) || null;

  return (
    <SiteContext.Provider value={{ sites, selectedSiteId, selectedSite, setSelectedSiteId, fetchSites, loading }}>
      {children}
    </SiteContext.Provider>
  );
}
