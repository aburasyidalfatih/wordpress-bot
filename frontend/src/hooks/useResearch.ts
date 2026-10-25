import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { apiFetch, isAbortError, NETWORK_ERROR, readJson, serverErrorMessage } from '@/lib/api';
import { useApiResource } from '@/hooks/useApiResource';
import { clampTitleCount } from '@/components/research/researchHelpers';
import type { JobStatusResponse, ResearchDataResponse, ResearchJobResult } from '@/lib/types';

const JOB_POLL_INTERVAL_MS = 2000;
// Safety net so the UI never spins forever. Normal ends (finished, failed,
// timed out, missing job) are reported by /api/job-status. Mirrors the backend
// (database.py): a job may wait RESEARCH_MAX_QUEUE_WAIT_SECONDS (6 h) in the
// queue before the dispatcher cancels it, then runs for its RQ timeout,
// research_job_timeout(n) = max(600 s, n x 360 s per category). /api/job-status
// reports the real timeout, which replaces the default below once known.
const RESEARCH_QUEUE_WAIT_MS = 6 * 60 * 60 * 1000;
const RESEARCH_MIN_TIMEOUT_MS = 600 * 1000;
const JOB_DURATION_MARGIN_MS = 15 * 60 * 1000;
const JOB_MAX_DURATION_MS = RESEARCH_QUEUE_WAIT_MS + RESEARCH_MIN_TIMEOUT_MS + JOB_DURATION_MARGIN_MS;
// Consecutive failed status checks (network error, 5xx, non-JSON body) tolerated
// before polling gives up. A 404 ends polling at once: the job does not exist.
const MAX_POLL_FAILURES = 3;
const JOB_END_MESSAGES: Record<string, string> = {
  failed: 'Riset gagal.',
  stopped: 'Riset dihentikan.',
  canceled: 'Riset dibatalkan.',
  cancelled: 'Riset dibatalkan.',
};
// Title generation is one synchronous AI call per request.
const TITLE_REQUEST_TIMEOUT_MS = 120_000;
const QUEUE_REDIRECT_DELAY_MS = 1500;
const RESUMED_JOB_MESSAGE = 'Riset untuk website ini sedang berjalan. Memantau progresnya...';
const TITLE_TIMEOUT_ERROR = `Pembuatan judul melebihi ${TITLE_REQUEST_TIMEOUT_MS / 1000} detik. Judul mungkin tetap dibuat — periksa Antrean.`;

export interface StatusMessage {
  text: string;
  tone: 'info' | 'success' | 'warning' | 'error';
  /** Hide the message once the in-place data reload that follows it completes. */
  untilReload?: boolean;
}

interface ApiResult {
  success?: boolean;
  error?: string;
  message?: string;
}

interface StartResearchResponse extends ApiResult {
  job_id?: string | null;
}

interface TitlesResponse extends ApiResult {
  queued?: number;
}

type TitleOutcome =
  | { kind: 'ok'; queued: number | null }
  | { kind: 'error'; status: number; error: string }
  | { kind: 'timeout' }
  | { kind: 'aborted' };

async function loadResearchData(siteId: number, signal: AbortSignal): Promise<ResearchDataResponse> {
  const res = await apiFetch(`/api/research_data?site_id=${siteId}&_t=${Date.now()}`, { signal });
  const payload = await readJson<ResearchDataResponse & ApiResult>(res);
  if (!res.ok || !payload.success) {
    throw new Error(payload.error || `Gagal memuat data riset (HTTP ${res.status}).`);
  }
  return payload as ResearchDataResponse;
}

/** Error text for a failed title request whose body had no `error` field. */
function titleServerError(status: number): string {
  const base = serverErrorMessage(status);
  // A gateway timeout does not mean the backend stopped: it may still queue titles.
  return status >= 500 ? `${base} Judul mungkin sudah dibuat — periksa Antrean.` : base;
}

/** POST /api/generate-titles with a timeout; `signal` cancels it early. */
async function requestTitles(siteId: number, category: string, count: number, signal: AbortSignal): Promise<TitleOutcome> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, TITLE_REQUEST_TIMEOUT_MS);
  const cancel = () => controller.abort();
  signal.addEventListener('abort', cancel);
  if (signal.aborted) controller.abort();

  try {
    const res = await apiFetch(`/api/generate-titles/${encodeURIComponent(category)}?site_id=${siteId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ count }),
      signal: controller.signal,
    });
    const payload = await readJson<TitlesResponse>(res);
    if (controller.signal.aborted) return timedOut ? { kind: 'timeout' } : { kind: 'aborted' };
    if (res.ok && payload.success) {
      return { kind: 'ok', queued: typeof payload.queued === 'number' ? payload.queued : null };
    }
    return { kind: 'error', status: res.status, error: payload.error || titleServerError(res.status) };
  } catch (e) {
    if (controller.signal.aborted || isAbortError(e)) return timedOut ? { kind: 'timeout' } : { kind: 'aborted' };
    return { kind: 'error', status: 0, error: NETWORK_ERROR };
  } finally {
    clearTimeout(timer);
    signal.removeEventListener('abort', cancel);
  }
}

function sentence(text: string | null | undefined): string {
  const trimmed = (text || '').trim().replace(/[.\s]+$/, '');
  return trimmed ? ` ${trimmed}.` : '';
}

/** Banner message for a finished research job, based on its reported outcome. */
function describeJobOutcome(result: ResearchJobResult | null | undefined): StatusMessage {
  if (!result) return { text: 'Analisis selesai! Data riset diperbarui.', tone: 'success', untilReload: true };
  const succeeded = Number(result.successful_categories) || 0;
  const failed = Number(result.failed_categories) || 0;
  const refunded = Number(result.refunded_credits) || 0;
  const refundNote = refunded > 0 ? ` ${refunded} kredit dikembalikan.` : '';

  if (result.skipped) {
    return { text: `Riset dilewati.${sentence(result.reason || 'Tidak ada kategori yang perlu diriset')}${refundNote}`, tone: 'warning' };
  }
  if (succeeded === 0) {
    return { text: `Riset selesai tetapi tidak ada kategori yang berhasil.${sentence(result.reason)}${refundNote}`, tone: 'error' };
  }
  if (failed > 0) {
    return { text: `Riset selesai sebagian: ${succeeded} kategori berhasil, ${failed} gagal.${refundNote}`, tone: 'warning' };
  }
  return { text: `Analisis selesai! ${succeeded} kategori berhasil diriset.${refundNote}`, tone: 'success', untilReload: true };
}

function toastStatus(status: StatusMessage) {
  if (status.tone === 'success') toast.success(status.text);
  else if (status.tone === 'warning') toast.warning(status.text);
  else if (status.tone === 'error') toast.error(status.text);
  else toast.info(status.text);
}

const refreshProfile = () => window.dispatchEvent(new Event('refresh-profile'));

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
  const [bulkGenerating, setBulkGenerating] = useState(false);

  const siteIdRef = useRef(siteId);
  const jobIdRef = useRef<string | null>(null);
  const titleRequestRef = useRef<AbortController | null>(null);
  const bulkRef = useRef<{ controller: AbortController; cancelledByUser: boolean } | null>(null);
  const queueRedirectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => { siteIdRef.current = siteId; }, [siteId]);
  useEffect(() => { jobIdRef.current = jobId; }, [jobId]);

  // Title requests and the redirect to the queue belong to the site they were
  // started for: abandon them when the site changes or the page unmounts.
  useEffect(() => {
    const titleRequest = titleRequestRef;
    const bulk = bulkRef;
    const queueRedirect = queueRedirectRef;
    return () => {
      titleRequest.current?.abort();
      titleRequest.current = null;
      bulk.current?.controller.abort();
      bulk.current = null;
      if (queueRedirect.current) clearTimeout(queueRedirect.current);
      queueRedirect.current = null;
    };
  }, [siteId]);

  const info = (text: string) => setStatus({ text, tone: 'info' });
  const fail = (text: string) => setStatus({ text, tone: 'error' });

  const redirectToQueue = () => {
    if (queueRedirectRef.current) clearTimeout(queueRedirectRef.current);
    queueRedirectRef.current = setTimeout(() => {
      queueRedirectRef.current = null;
      navigate('/queue');
    }, QUEUE_REDIRECT_DELAY_MS);
  };

  // A research job belongs to the site it was started for: when the selected
  // site changes, stop tracking it (this also stops the polling effect below).
  const [trackedSiteId, setTrackedSiteId] = useState(siteId);
  if (trackedSiteId !== siteId) {
    setTrackedSiteId(siteId);
    setJobId(null);
    setResearching(false);
    setResearchingCategory(null);
    setProgress(0);
    setStatus(null);
    setGeneratingFor(null);
    setBulkGenerating(false);
  }

  // Data reloads in place; a message that only announced the reload goes away
  // once it completes.
  const [wasLoading, setWasLoading] = useState(resource.loading);
  if (wasLoading !== resource.loading) {
    setWasLoading(resource.loading);
    if (!resource.loading && status?.untilReload) setStatus(null);
  }

  // Resume a research job that is still running for this site, e.g. after the
  // page was left or reloaded, so its progress shows and the buttons stay locked.
  useEffect(() => {
    if (!siteId) return;
    const controller = new AbortController();
    (async () => {
      try {
        const res = await apiFetch(`/api/research/active?site_id=${siteId}`, { signal: controller.signal });
        if (!res.ok) return; // Older backends do not have this endpoint.
        const payload = await readJson<StartResearchResponse>(res);
        const activeJobId = payload.job_id;
        if (controller.signal.aborted || !payload.success || !activeJobId || jobIdRef.current === activeJobId) return;
        setJobId(activeJobId);
        setResearching(true);
        setResearchingCategory(null);
        setProgress(0);
        setStatus({ text: RESUMED_JOB_MESSAGE, tone: 'info' });
      } catch (e) {
        if (!isAbortError(e) && import.meta.env.DEV) console.error('Failed to check the active research job', e);
      }
    })();
    return () => controller.abort();
  }, [siteId]);

  useEffect(() => {
    if (!jobId) return;

    const controller = new AbortController();
    const startedAt = Date.now();
    let maxDurationMs = JOB_MAX_DURATION_MS;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let failures = 0;
    let stopped = false;

    const stopPolling = (outcome: StatusMessage | null) => {
      if (stopped) return;
      stopped = true;
      controller.abort();
      setResearching(false);
      setResearchingCategory(null);
      setJobId(null);
      // Credits were charged, and failed categories refunded: update the balance.
      refreshProfile();
      if (outcome) {
        setStatus(outcome);
        toastStatus(outcome);
      }
    };

    const schedule = () => {
      if (!stopped) timer = setTimeout(poll, JOB_POLL_INTERVAL_MS);
    };

    const transientFailure = (detail: string) => {
      failures += 1;
      if (failures >= MAX_POLL_FAILURES) {
        stopPolling({
          text: `Gagal memantau status riset (${detail}). Riset mungkin masih berjalan — muat ulang halaman untuk melihat hasil terbaru.`,
          tone: 'error',
        });
      } else {
        schedule();
      }
    };

    const poll = async () => {
      if (stopped) return;
      if (Date.now() - startedAt > maxDurationMs) {
        stopPolling({ text: 'Riset terlalu lama dan pemantauan dihentikan. Muat ulang halaman untuk melihat hasil terbaru.', tone: 'error' });
        return;
      }

      let res: Response;
      try {
        res = await apiFetch(`/api/job-status/${encodeURIComponent(jobId)}`, { signal: controller.signal });
      } catch (e) {
        if (stopped || isAbortError(e)) return;
        transientFailure('koneksi terputus');
        return;
      }
      const payload = await readJson<JobStatusResponse>(res);
      if (stopped) return;

      if (res.status === 404) {
        stopPolling({ text: `Tugas riset tidak ditemukan.${sentence(payload.error)}`, tone: 'error' });
        return;
      }
      if (!res.ok || !payload.success || typeof payload.status !== 'string') {
        transientFailure(payload.error || `HTTP ${res.status}`);
        return;
      }
      failures = 0;
      const timeoutSeconds = Number(payload.timeout_seconds);
      if (Number.isFinite(timeoutSeconds) && timeoutSeconds > 0) {
        maxDurationMs = Math.max(JOB_MAX_DURATION_MS,
          RESEARCH_QUEUE_WAIT_MS + timeoutSeconds * 1000 + JOB_DURATION_MARGIN_MS);
      }

      if (payload.status === 'finished') {
        stopPolling(describeJobOutcome(payload.result));
        reload();
        return;
      }
      if (JOB_END_MESSAGES[payload.status]) {
        stopPolling({ text: JOB_END_MESSAGES[payload.status], tone: 'error' });
        reload();
        return;
      }

      const value = Math.round(Number(payload.progress) || 0);
      setProgress(Math.min(100, Math.max(0, value)));
      setStatus({ text: payload.message || 'Riset sedang diproses...', tone: 'info' });
      schedule();
    };

    // Check right away so a resumed job shows its real progress immediately.
    timer = setTimeout(poll, 0);

    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
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
      const result = await readJson<ApiResult>(res);
      if (siteIdRef.current !== siteId) return;
      if (res.ok && result.success) {
        setStatus(null);
        toast.success(result.message || 'Data riset berhasil dibersihkan.');
        reload();
      } else {
        fail(`Gagal menghapus riset: ${result.error || serverErrorMessage(res.status)}`);
      }
    } catch {
      if (siteIdRef.current === siteId) fail(NETWORK_ERROR);
    }
  };

  const startResearch = async (categoryName?: string) => {
    if (!siteId || researching || bulkGenerating) return;
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
      const result = await readJson<StartResearchResponse>(res);
      const startedJobId = result.job_id;
      if (res.ok && result.success && startedJobId) refreshProfile();
      // The user switched sites while the job was starting; don't track it here.
      if (siteIdRef.current !== siteId) return;

      if (res.status === 409 && startedJobId) {
        // A job for this site is already running (and nothing was charged): follow it.
        toast.info('Riset untuk website ini sudah berjalan. Melanjutkan pemantauan riset tersebut.');
        setResearchingCategory(null);
        info(RESUMED_JOB_MESSAGE);
        setJobId(startedJobId);
      } else if (res.ok && result.success && startedJobId) {
        setJobId(startedJobId);
      } else {
        stopWithError(result.error || (res.ok ? 'Riset gagal dimulai.' : serverErrorMessage(res.status)));
      }
    } catch {
      if (siteIdRef.current === siteId) stopWithError(NETWORK_ERROR);
    }
  };

  const generateTitles = async (category: string, count: number) => {
    if (!siteId || generatingFor || bulkGenerating) return;
    const controller = new AbortController();
    titleRequestRef.current = controller;
    setGeneratingFor(category);
    const outcome = await requestTitles(siteId, category, clampTitleCount(count, 1), controller.signal);
    // Aborted when the site changed or the page unmounted: the result is not for this page.
    if (outcome.kind === 'aborted' || controller.signal.aborted) return;
    titleRequestRef.current = null;
    setGeneratingFor(null);
    // Title generation can be billed (it may answer 402); keep the balance current.
    if (outcome.kind === 'ok') refreshProfile();

    if (outcome.kind === 'ok') {
      if (outcome.queued === 0) {
        setStatus({ text: `Tidak ada judul baru untuk "${category}" yang ditambahkan ke antrean.`, tone: 'warning' });
        return;
      }
      const queuedText = outcome.queued === null ? 'Judul' : `${outcome.queued} judul`;
      setStatus({ text: `Berhasil: ${queuedText} untuk "${category}" dimasukkan ke antrean. Membuka Antrean...`, tone: 'success' });
      redirectToQueue();
      return;
    }
    const error = outcome.kind === 'timeout' ? TITLE_TIMEOUT_ERROR : outcome.error;
    fail(`Gagal membuat judul untuk "${category}": ${error}`);
    toast.error(`Gagal membuat judul untuk "${category}".`);
  };

  /** Requests titles category by category; `items` counts are clamped to 0..20 (0 = skip). */
  const generateTitlesInBulk = async (items: { category: string; count: number }[]) => {
    if (!siteId || bulkRef.current || researching) return;
    const jobs = items
      .map(item => ({ category: item.category, count: clampTitleCount(item.count, 0) }))
      .filter(item => item.count > 0);
    if (jobs.length === 0) return;

    const run = { controller: new AbortController(), cancelledByUser: false };
    bulkRef.current = run;
    setBulkGenerating(true);
    setProgress(0);
    info('Memulai pembuatan judul massal...');

    let queuedTotal = 0;
    // Successful responses from a backend that does not report `queued`.
    let unreportedSuccesses = 0;
    let failedCategories = 0;
    let stopError: string | null = null;

    for (let i = 0; i < jobs.length && !run.controller.signal.aborted; i++) {
      const { category, count } = jobs[i];
      info(`Membuat ${count} judul untuk "${category}" (${i + 1}/${jobs.length})...`);
      setProgress(Math.round((i / jobs.length) * 100));
      const outcome = await requestTitles(siteId, category, count, run.controller.signal);
      if (outcome.kind === 'aborted') break;
      if (outcome.kind === 'ok') {
        if (outcome.queued === null) unreportedSuccesses += 1;
        else queuedTotal += outcome.queued;
      } else if (outcome.kind === 'timeout') {
        failedCategories += 1;
        toast.error(`Gagal membuat judul untuk "${category}": ${TITLE_TIMEOUT_ERROR}`);
      } else if (outcome.status === 402 || outcome.status === 429) {
        // Out of credits or AI quota: every remaining request would fail the same way.
        stopError = outcome.error;
        break;
      } else {
        failedCategories += 1;
        toast.error(`Gagal membuat judul untuk "${category}": ${outcome.error}`);
      }
    }

    // The site changed or the page unmounted: nothing here belongs to the new page.
    if (run.controller.signal.aborted && !run.cancelledByUser) return;
    bulkRef.current = null;
    setBulkGenerating(false);
    setProgress(100);
    refreshProfile();

    const queuedText = `${queuedTotal} judul`
      + (unreportedSuccesses > 0 ? ` (ditambah judul dari ${unreportedSuccesses} kategori yang jumlahnya tidak dilaporkan server)` : '');
    const anyQueued = queuedTotal > 0 || unreportedSuccesses > 0;
    const failedNote = failedCategories > 0 ? ` ${failedCategories} kategori gagal.` : '';

    if (run.cancelledByUser) {
      const text = `Pembuatan judul massal dibatalkan. ${queuedText} sudah masuk antrean; permintaan yang sedang berjalan mungkin tetap selesai di server.`;
      setStatus({ text, tone: 'warning' });
      toast.warning('Pembuatan judul massal dibatalkan.');
    } else if (stopError) {
      setStatus({ text: `Pembuatan judul massal dihentikan: ${stopError} ${queuedText} sudah masuk antrean.${failedNote}`, tone: 'error' });
      toast.error(`Pembuatan judul massal dihentikan: ${stopError}`);
    } else if (anyQueued) {
      setStatus({
        text: `Selesai! ${queuedText} berhasil ditambahkan ke antrean.${failedNote} Membuka Antrean...`,
        tone: failedCategories > 0 ? 'warning' : 'success',
      });
      redirectToQueue();
    } else {
      setStatus({ text: `Tidak ada judul yang ditambahkan ke antrean.${failedNote}`, tone: 'error' });
    }
  };

  const cancelBulkGeneration = () => {
    const run = bulkRef.current;
    if (!run) return;
    run.cancelledByUser = true;
    run.controller.abort();
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
    bulkGenerating,
    clearResearch,
    startResearch,
    generateTitles,
    generateTitlesInBulk,
    cancelBulkGeneration,
  };
}
