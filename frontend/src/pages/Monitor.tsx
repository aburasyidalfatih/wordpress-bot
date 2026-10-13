import { useState, useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import { apiFetch, isAbortError } from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Activity, HardDrive, Cpu, MemoryStick, Clock, Download } from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { MonitorApiResponse, MonitorServiceInfo } from '@/lib/types';

const POLL_INTERVAL_MS = 5000;

function UsageCard({ title, icon, percent }: { title: string; icon: ReactNode; percent: number }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        {icon}
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{percent}%</div>
        <div className="w-full bg-secondary h-2 mt-2 rounded-full overflow-hidden">
          <div className="bg-primary h-full transition-all" style={{ width: `${percent}%` }} />
        </div>
      </CardContent>
    </Card>
  );
}

function schedulerBadge(running: boolean | null | undefined) {
  if (running === true) return { label: 'Berjalan', className: 'bg-green-100 text-green-800' };
  if (running === false) return { label: 'Berhenti', className: 'bg-red-100 text-red-800' };
  return { label: 'Tidak diketahui', className: 'bg-yellow-100 text-yellow-800' };
}

function ServicesCard({ serviceInfo }: { serviceInfo?: MonitorServiceInfo }) {
  const badge = schedulerBadge(serviceInfo?.scheduler_running);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Activity className="h-5 w-5"/> Layanan Latar Belakang</CardTitle>
        <CardDescription>Status scheduler otomatisasi dan worker latar belakang.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex justify-between items-center py-2 border-b">
          <span className="text-muted-foreground">Status Scheduler</span>
          <span
            title={serviceInfo?.scheduler_detail || serviceInfo?.scheduler_last_heartbeat || undefined}
            className={`px-2 py-1 rounded-md text-xs font-medium ${badge.className}`}
          >
            {badge.label}
          </span>
        </div>
        <div className="flex justify-between items-center py-2 border-b">
          <span className="text-muted-foreground">Job Aktif</span>
          <span className="font-medium">
            {serviceInfo?.scheduler_jobs != null ? `${serviceInfo.scheduler_jobs} job menunggu` : '—'}
          </span>
        </div>
        <div className="flex justify-between items-center py-2 border-b">
          <span className="text-muted-foreground">Ukuran File Log</span>
          <span className="font-medium">{serviceInfo?.log_size ? serviceInfo.log_size.toFixed(2) : '0.00'} MB</span>
        </div>
      </CardContent>
    </Card>
  );
}

async function downloadLogs() {
  const res = await apiFetch('/download-logs');
  if (!res.ok) throw new Error('Gagal mengunduh log.');
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `bot_log_${new Date().toISOString().replace(/[:.]/g, '-')}.log`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

export default function Monitor() {
  const [data, setData] = useState<MonitorApiResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const fetchMonitor = () => {
      // Abort any in-flight request before starting a new one
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      apiFetch('/api/monitor', { signal: controller.signal })
        .then(res => { if (!res.ok) throw new Error('HTTP ' + res.status); return res.json(); })
        .then(d => { setData(d); setLoading(false); })
        .catch(err => { if (!isAbortError(err)) setLoading(false); });
    };
    fetchMonitor();
    const interval = setInterval(fetchMonitor, POLL_INTERVAL_MS);
    return () => { controllerRef.current?.abort(); clearInterval(interval); };
  }, []);

  const handleDownloadLogs = async () => {
    setDownloading(true);
    try {
      await downloadLogs();
    } catch (error) {
      if (import.meta.env.DEV) console.error(error);
    } finally {
      setDownloading(false);
    }
  };

  if (loading && !data) return <div className="p-8">Memuat data monitor...</div>;

  const { system_info, service_info, recent_errors } = data || {};

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-primary to-indigo-600 dark:from-primary dark:to-indigo-400 bg-clip-text text-transparent flex items-center gap-2">
          <Activity className="h-8 w-8 text-primary" /> Monitor Sistem
        </h1>
        <p className="text-muted-foreground">Kesehatan dan metrik performa worker AutoWP Anda secara real-time.</p>
      </div>

      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
        <UsageCard title="Penggunaan CPU" icon={<Cpu className="h-4 w-4 text-muted-foreground" />} percent={system_info?.cpu_percent ?? 0} />
        <UsageCard title="Penggunaan Memori" icon={<MemoryStick className="h-4 w-4 text-muted-foreground" />} percent={system_info?.memory_percent ?? 0} />
        <UsageCard title="Penggunaan Disk" icon={<HardDrive className="h-4 w-4 text-muted-foreground" />} percent={system_info?.disk_percent ?? 0} />

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Uptime</CardTitle>
            <Clock className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="font-bold text-sm truncate">{system_info?.uptime}</div>
            <p className="text-xs text-muted-foreground mt-2">Lama server berjalan</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <ServicesCard serviceInfo={service_info} />

        <Card>
          <CardHeader className="flex flex-row items-start justify-between">
            <div>
              <CardTitle>Error Sistem Terbaru</CardTitle>
              <CardDescription>Baris ERROR terbaru dari log aplikasi.</CardDescription>
            </div>
            <Button variant="outline" size="sm" className="flex items-center gap-2" onClick={handleDownloadLogs} disabled={downloading}>
              <Download className="h-4 w-4" /> {downloading ? 'Mengunduh...' : 'Unduh Log'}
            </Button>
          </CardHeader>
          <CardContent>
            <div className="bg-muted/30 p-4 rounded-md font-mono text-xs overflow-x-auto max-h-[250px] overflow-y-auto space-y-2">
              {recent_errors && recent_errors.length > 0 ? (
                recent_errors.map((err, i) => (
                  <div key={i} className="text-red-500 whitespace-pre-wrap border-b border-red-500/10 pb-2">{err}</div>
                ))
              ) : (
                <div className="text-green-600 font-medium text-center py-8">Tidak ada error terbaru. Sistem dalam kondisi sehat!</div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
