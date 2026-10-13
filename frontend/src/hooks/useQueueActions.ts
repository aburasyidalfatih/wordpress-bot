import { toast } from 'sonner';
import { arrayMove } from '@dnd-kit/sortable';
import type { DragEndEvent } from '@dnd-kit/core';
import { apiFetch, NETWORK_ERROR } from '@/lib/api';
import type { useQueueData } from '@/hooks/useQueueData';

const SERVER_ERROR = 'Terjadi kesalahan pada server.';
// Regeneration runs in the background; stop showing the spinner after this long
// even if polling hasn't picked up the result yet.
const IMAGE_REGEN_TIMEOUT_MS = 60_000;
const ARTICLE_REGEN_TIMEOUT_MS = 120_000;

function jsonRequest(url: string, method: string, body?: unknown) {
  return apiFetch(url, {
    method,
    ...(body !== undefined ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}),
  });
}

function logError(error: unknown) {
  if (import.meta.env.DEV) console.error(error);
}

/** Mutations of the content queue and its history. Each one shows its own toast. */
export function useQueueActions(siteId: number | null, queue: ReturnType<typeof useQueueData>) {
  const { items, setItems, loadQueue, setRegeneratingIds, siteIdRef } = queue;
  const setRegenerating = (logId: number, value: boolean) =>
    setRegeneratingIds(prev => ({ ...prev, [logId]: value }));

  const reorder = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    // Compute the new order outside a state updater so the request is sent
    // exactly once (updaters may run twice in StrictMode).
    const previousItems = items;
    const oldIndex = previousItems.findIndex((i) => i.id === active.id);
    const newIndex = previousItems.findIndex((i) => i.id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;
    const newItems = arrayMove(previousItems, oldIndex, newIndex);
    const requestSiteId = siteId;
    setItems(newItems);

    jsonRequest('/api/queue/reorder', 'POST', { ids: newItems.map((i) => i.id) })
      .then(async (res) => {
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.error || SERVER_ERROR);
        }
      })
      .catch(err => {
        logError(err);
        toast.error('Gagal menyimpan urutan antrean.');
        if (siteIdRef.current === requestSiteId) {
          setItems(previousItems); // Revert to the old order
        }
      });
  };

  const deleteItem = async (id: number) => {
    try {
      const res = await jsonRequest('/api/queue', 'DELETE', { id });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        if (res.status === 409) {
          toast.error(data.error || 'Artikel sedang diposting dan tidak dapat dihapus.');
        } else {
          toast.error('Gagal menghapus: ' + (data.error || SERVER_ERROR));
        }
      }
      loadQueue();
    } catch (e) {
      logError(e);
      toast.error(NETWORK_ERROR);
    }
  };

  const regenerate = async (logId: number, kind: 'image' | 'article') => {
    setRegenerating(logId, true);
    try {
      const res = await apiFetch(`/api/queue/history/regenerate-${kind}/${logId}`, { method: 'POST' });
      const data = await res.json();
      if (!data.success) {
        toast.error('Gagal: ' + (data.error || SERVER_ERROR));
        setRegenerating(logId, false);
        return;
      }
      if (kind === 'article') toast.success('Artikel sedang dibuat ulang di latar belakang...');
      // Leave the spinner on; polling refreshes the list and hides the button when done.
      setTimeout(() => setRegenerating(logId, false), kind === 'article' ? ARTICLE_REGEN_TIMEOUT_MS : IMAGE_REGEN_TIMEOUT_MS);
    } catch (e) {
      logError(e);
      toast.error(NETWORK_ERROR);
      setRegenerating(logId, false);
    }
  };

  const deleteHistory = async (logId: number) => {
    try {
      const res = await apiFetch(`/api/queue/history/${logId}`, { method: 'DELETE' });
      const data = await res.json();
      if (!data.success) {
        toast.error('Gagal menghapus riwayat: ' + (data.error || SERVER_ERROR));
        return;
      }
      // The log is always removed; wp_error is set when the WordPress article couldn't be trashed.
      if (data.wp_error) {
        toast.warning(data.message || `Riwayat dihapus, tetapi artikel di WordPress gagal dihapus: ${data.wp_error}`);
      } else {
        toast.success(data.message || 'Riwayat berhasil dihapus.');
      }
      loadQueue();
    } catch (e) {
      logError(e);
      toast.error(NETWORK_ERROR);
    }
  };

  /** Returns true when the title was added. */
  const addTitle = async (title: string, category: string) => {
    try {
      const res = await jsonRequest('/api/queue', 'POST', { site_id: siteId, title, category, target_keywords: '' });
      const data = await res.json();
      if (data.success) {
        toast.success('Artikel berhasil ditambahkan ke antrean!');
        loadQueue();
        return true;
      }
      toast.error('Gagal menambahkan ke antrean: ' + (data.error || SERVER_ERROR));
    } catch (e) {
      logError(e);
      toast.error(NETWORK_ERROR);
    }
    return false;
  };

  const shuffle = async () => {
    if (!siteId || items.length <= 1) return;
    try {
      const res = await jsonRequest('/api/queue/shuffle', 'POST', { site_id: siteId });
      const data = await res.json();
      if (data.success) {
        toast.success(data.message || 'Antrean berhasil diacak!');
        loadQueue(true);
      } else {
        toast.error('Gagal mengacak: ' + (data.error || SERVER_ERROR));
      }
    } catch (e) {
      logError(e);
      toast.error(NETWORK_ERROR);
    }
  };

  const clearQueue = async () => {
    if (!siteId) return;
    try {
      const res = await jsonRequest('/api/queue/clear', 'POST', { site_id: siteId });
      const data = await res.json();
      if (data.success) {
        toast.success('Semua antrean berhasil dihapus!');
        loadQueue(true);
      } else {
        toast.error('Gagal menghapus antrean: ' + (data.error || SERVER_ERROR));
      }
    } catch (e) {
      logError(e);
      toast.error(NETWORK_ERROR);
    }
  };

  const postNow = async (id: number) => {
    // Optimistic update so the progress bar shows instantly.
    setItems(current => current.map(item => (item.id === id ? { ...item, status: 'posting' } : item)));
    try {
      const res = await apiFetch(`/api/queue/post/${id}`, { method: 'POST' });
      const data = await res.json().catch(() => ({}));
      if (res.status === 409) {
        toast.error(data.error || 'Artikel ini sedang diposting.');
      } else if (data.success) {
        toast.success('Artikel sedang diproses!');
        // Posting reserves a credit; refresh the credit badge in the layout.
        window.dispatchEvent(new Event('refresh-profile'));
      } else {
        toast.error('Gagal memposting artikel: ' + (data.error || SERVER_ERROR));
      }
    } catch (e) {
      logError(e);
      toast.error(NETWORK_ERROR);
    }
    loadQueue(true);
  };

  /** Returns true when the edit was saved. */
  const saveEdit = async (id: number, title: string, keywords: string, sendKeywords: boolean) => {
    try {
      // Only send target_keywords when the current value is known (or the user
      // typed one) so an older payload without the field can't wipe it.
      const res = await jsonRequest(`/api/queue/edit/${id}`, 'POST', {
        title,
        ...(sendKeywords ? { target_keywords: keywords } : {}),
      });
      const data = await res.json();
      if (data.success) {
        toast.success('Perubahan berhasil disimpan!');
        loadQueue(true);
        return true;
      }
      toast.error('Gagal menyimpan perubahan: ' + (data.error || SERVER_ERROR));
    } catch (e) {
      logError(e);
      toast.error(NETWORK_ERROR);
    }
    return false;
  };

  return { reorder, deleteItem, regenerate, deleteHistory, addTitle, shuffle, clearQueue, postNow, saveEdit };
}
