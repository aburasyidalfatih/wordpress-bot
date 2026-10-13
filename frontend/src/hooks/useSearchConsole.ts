import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { apiFetch, errorMessage } from '@/lib/api';
import { useSiteContext } from '@/hooks/useSiteContext';
import type { GscProperty, SiteDraft } from '@/lib/types';

async function requestJson(url: string, init: RequestInit, fallbackError: string) {
  const res = await apiFetch(url, init);
  const data = await res.json();
  if (!res.ok || !data.success) throw new Error(data.error || fallbackError);
  return data;
}

/** Google Search Console actions for the website being edited. */
export function useSearchConsole(siteId: number | undefined, updateSite: (patch: SiteDraft) => void) {
  const { fetchSites } = useSiteContext();
  const [properties, setProperties] = useState<GscProperty[]>([]);
  const [busy, setBusy] = useState(false);
  const base = `/api/search-console/sites/${siteId}`;

  const connect = async () => {
    if (!siteId) return;
    setBusy(true);
    try {
      const data = await requestJson(`${base}/authorize`, { method: 'POST' }, 'Gagal memulai OAuth Google.');
      window.location.assign(data.authorization_url);
    } catch (error) {
      toast.error(errorMessage(error, 'Gagal menghubungkan Search Console.'));
      setBusy(false);
    }
  };

  const loadProperties = async () => {
    if (!siteId) return;
    setBusy(true);
    try {
      const data = await requestJson(`${base}/properties`, {}, 'Gagal mengambil property.');
      const list: GscProperty[] = data.properties || [];
      setProperties(list);
      toast.success(`${list.length} property ditemukan.`);
    } catch (error) {
      toast.error(errorMessage(error, 'Gagal mengambil property Search Console.'));
    } finally {
      setBusy(false);
    }
  };

  const selectProperty = async (propertyUrl: string) => {
    if (!siteId) return;
    setBusy(true);
    try {
      await requestJson(`${base}/property`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ property_url: propertyUrl }),
      }, 'Gagal menyimpan property.');
      updateSite({ gsc_property_url: propertyUrl });
      toast.success('Property Search Console tersimpan.');
      await fetchSites();
    } catch (error) {
      toast.error(errorMessage(error, 'Gagal menyimpan property.'));
    } finally {
      setBusy(false);
    }
  };

  const sync = async () => {
    if (!siteId) return;
    setBusy(true);
    try {
      await requestJson(`${base}/sync`, { method: 'POST' }, 'Gagal memulai sinkronisasi.');
      toast.success('Sinkronisasi berjalan di latar belakang. Periksa Intelligence Hub beberapa saat lagi.');
    } catch (error) {
      toast.error(errorMessage(error, 'Gagal memulai sinkronisasi.'));
    } finally {
      setBusy(false);
    }
  };

  const disconnect = async () => {
    if (!siteId) return;
    setBusy(true);
    try {
      const res = await apiFetch(`${base}/disconnect`, { method: 'POST' });
      if (!res.ok) throw new Error('Gagal memutus koneksi.');
      updateSite({ gsc_connected: false, gsc_property_url: null });
      setProperties([]);
      await fetchSites();
      toast.success('Koneksi Search Console diputus.');
    } catch (error) {
      toast.error(errorMessage(error, 'Gagal memutus koneksi.'));
    } finally {
      setBusy(false);
    }
  };

  return { properties, busy, connect, loadProperties, selectProperty, sync, disconnect };
}

/**
 * Shows the result of the Google OAuth redirect (?gsc=connected|error) once and
 * removes the query string so a reload doesn't show it again.
 */
export function useSearchConsoleReturnToast() {
  const { fetchSites } = useSiteContext();
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const status = params.get('gsc');
    if (!status) return;
    if (status === 'connected') {
      toast.success('Google Search Console berhasil terhubung.');
      fetchSites();
    } else {
      toast.error(params.get('message') || 'Gagal menghubungkan Google Search Console.');
    }
    window.history.replaceState({}, '', window.location.pathname);
  }, [fetchSites]);
}
