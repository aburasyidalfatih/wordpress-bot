import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { apiFetch, isAbortError, NETWORK_ERROR } from '@/lib/api';
import { useApiResource } from '@/hooks/useApiResource';
import type { ResearchDataResponse } from '@/lib/types';

const JOB_POLL_INTERVAL_MS = 2000;
// Safety net so the UI never spins forever. Normal ends (finished, failed,
// timed out, missing job) are reported by /api/job-status; the backend allows
// 180 s per category and the job may also wait behind others in the queue.
const JOB_MAX_DURATION_MS = 3 * 60 * 60 * 1000;
const JOB_END_MESSAGES: Record<string, string> = {
  failed: 'Riset gagal.',
  stopped: 'Riset dihentikan.',
  canceled: 'Riset dibatalkan.',
  cancelled: 'Riset dibatalkan.',
};

export interface StatusMessage {
  text: string;
  tone: 'info' | 'error';
}

async function loadResearchData(siteId: number, signal: AbortSignal): Promise<ResearchDataResponse> {
  const res = await apiFetch(`/api/research_data?site_id=${siteId}&_t=${Date.now()}`, { signal });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok || !payload.success) {
    throw new Error(payload.error || `Gagal memuat data riset (${res.status}).`);
  }
  return payload;
}

function generateTitlesRequest(siteId: number, category: string, count: number) {
  return apiFetch(`/api/generate-titles/${encodeURIComponent(category)}?site_id=${siteId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ count }),
  }).then(res => res.json());
}

/** Research data of the selected website plus the research/title-generation jobs. */
export function useResearch(siteId: number | null) {
  const navigate = useNavigate();
  const resource = useApiResource<ResearchDataResponse>(
    siteId ? `/api/research_data?site_id=${siteId}` : null,
    signal => loadResearchData(siteId as number, signal),
  );
  const { reload } = resource;

  const [researching, setResearching] = useState(false);
  const [researchingCategory, setResearchingCategory] = useState<string | null>(null);
  const [status, setStatus] = useState<StatusMessage | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [generatingFor, setGeneratingFor] = useState<string | null>(null);

  const siteIdRef = useRef(siteId);
  const reloadTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => { siteIdRef.current = siteId; }, [siteId]);
  useEffect(() => () => {
    if (reloadTimeoutRef.current) clearTimeout(reloadTimeoutRef.current);
  }, []);

  const info = (text: string) => setStatus({ text, tone: 'info' });
  const fail = (text: string) => setStatus({ text, tone: 'error' });

  // A research job belongs to the site it was started for: when the selected
  // site changes, stop tracking it (this also stops the polling effect below).
  const [jobSiteId, setJobSiteId] = useState(siteId);
  if (jobSiteId !== siteId) {
    setJobSiteId(siteId);
    setJobId(null);
    setResearching(false);
    setResearchingCategory(null);
    setProgress(0);
    setStatus(null);
  }

  useEffect(() => {
    if (!jobId) return;

    const controller = new AbortController();
    const startedAt = Date.now();
    let stopped = false;

    const stopPolling = (errorText?: string) => {
      if (stopped) return;
      stopped = true;
      clearInterval(interval);
      controller.abort();
      setResearching(false);
      setResearchingCategory(null);
      setJobId(null);
      if (errorText) {
        setStatus({ text: errorText, tone: 'error' });
        toast.error(errorText);
      }
    };

    const interval = setInterval(async () => {
      if (stopped) return;
      if (Date.now() - startedAt > JOB_MAX_DURATION_MS) {
        stopPolling('Riset terlalu lama dan pemantauan dihentikan. Muat ulang halaman untuk melihat hasil terbaru.');
        return;
      }
      try {
        const res = await apiFetch(`/api/job-status/${jobId}`, { signal: controller.signal });
        const result = await res.json().catch(() => ({}));
        if (stopped) return;

        if (res.status === 404 || !result.success) {
          stopPolling(result.error ? `Riset gagal: ${result.error}` : `Tugas riset tidak ditemukan (${res.status}).`);
          return;
        }

        setProgress(result.progress);
        setStatus({ text: `${result.progress}% - ${result.message}`, tone: 'info' });

        if (result.status === 'finished') {
          stopPolling();
          setStatus({ text: 'Analisis selesai! Memuat ulang data...', tone: 'info' });
          if (reloadTimeoutRef.current) clearTimeout(reloadTimeoutRef.current);
          reloadTimeoutRef.current = setTimeout(() => {
            reloadTimeoutRef.current = null;
            reload();
          }, 1000);
        } else if (JOB_END_MESSAGES[result.status]) {
          stopPolling(JOB_END_MESSAGES[result.status]);
        }
      } catch (e) {
        if (isAbortError(e)) return;
        if (import.meta.env.DEV) console.error('Polling error', e);
      }
    }, JOB_POLL_INTERVAL_MS);

    return () => {
      stopped = true;
      clearInterval(interval);
      controller.abort();
    };
  }, [jobId, reload]);

  const clearResearch = async () => {
    if (!siteId) return;
    try {
      const res = await apiFetch('/api/clear-research', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ site_id: siteId }),
      });
      const result = await res.json();
      if (result.success) {
        info(result.message);
        reload();
      } else {
        fail('Gagal menghapus riset: ' + result.error);
      }
    } catch {
      fail(NETWORK_ERROR);
    }
  };

  const startResearch = async (categoryName?: string) => {
    if (!siteId) return;
    setResearching(true);
    setResearchingCategory(categoryName || 'all');
    setProgress(0);
    info(categoryName ? `Memulai riset mendalam untuk kategori "${categoryName}"...` : 'Memulai riset mendalam untuk semua kategori...');
    const stopWithError = (text: string) => {
      fail(text);
      setResearching(false);
      setResearchingCategory(null);
    };
    try {
      const url = categoryName
        ? `/manual-research?site_id=${siteId}&category=${encodeURIComponent(categoryName)}`
        : `/manual-research?site_id=${siteId}`;
      const res = await apiFetch(url, { method: 'POST' });
      const result = await res.json();
      if (result.success && result.job_id) {
        window.dispatchEvent(new Event('refresh-profile'));
        // The user switched sites while the job was starting; don't track it here.
        if (siteIdRef.current !== siteId) return;
        setJobId(result.job_id);
      } else {
        stopWithError(result.error || 'Riset gagal dimulai.');
      }
    } catch {
      stopWithError(NETWORK_ERROR);
    }
  };

  const generateTitles = async (category: string, count: number) => {
    if (!siteId) return;
    setGeneratingFor(category);
    try {
      const result = await generateTitlesRequest(siteId, category, count);
      if (result.success) {
        info(`Berhasil: ${result.message}`);
        setTimeout(() => navigate('/queue'), 1500);
      } else {
        fail(result.error || 'Gagal membuat judul.');
      }
    } catch {
      fail(NETWORK_ERROR);
    } finally {
      setGeneratingFor(null);
    }
  };

  const generateTitlesInBulk = async (counts: Record<string, number>) => {
    if (!siteId) return;
    setResearching(true);
    info('Memulai pembuatan judul massal...');

    let totalGenerated = 0;
    const categories = Object.entries(counts).filter(([, count]) => count > 0);

    for (let i = 0; i < categories.length; i++) {
      const [category, count] = categories[i];
      info(`Membuat ${count} judul untuk ${category} (${i + 1}/${categories.length})...`);
      setProgress(Math.round((i / categories.length) * 100));
      try {
        const result = await generateTitlesRequest(siteId, category, count);
        if (result.success) {
          totalGenerated += count;
        } else {
          toast.error(`Gagal membuat judul untuk ${category}: ${result.error}`);
        }
      } catch (err) {
        if (import.meta.env.DEV) console.error('Failed for', category, err);
        toast.error(`Gagal terhubung ke server saat membuat judul untuk ${category}.`);
      }
    }

    setProgress(100);
    info(`Selesai! ${totalGenerated} judul berhasil ditambahkan ke antrean.`);
    setResearching(false);
    setTimeout(() => navigate('/queue'), 2000);
  };

  return {
    data: resource.data,
    loading: resource.loading,
    loadError: resource.error,
    reload,
    researching,
    researchingCategory,
    status,
    progress,
    generatingFor,
    clearResearch,
    startResearch,
    generateTitles,
    generateTitlesInBulk,
  };
}
