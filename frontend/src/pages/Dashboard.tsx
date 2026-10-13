import { fetchJson } from '@/lib/api';
import EmptyState from '@/components/EmptyState';
import { ErrorState } from '@/components/ErrorState';
import { Skeleton } from '@/components/ui/skeleton';
import { useSiteContext } from '@/hooks/useSiteContext';
import { useApiResource } from '@/hooks/useApiResource';
import { KpiCards } from '@/components/dashboard/KpiCards';
import { InsightsCard, RecentActivityCard } from '@/components/dashboard/ActivityCards';
import { CategoryPerformanceTable, EngagementChart } from '@/components/dashboard/CategoryPerformance';
import type { DashboardApiResponse } from '@/lib/types';

function DashboardSkeleton() {
  return (
    <div className="space-y-6 p-2 md:p-6 pb-24">
      <div className="flex flex-col gap-2">
        <Skeleton className="h-10 w-[200px]" />
        <Skeleton className="h-4 w-[300px]" />
      </div>
      <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
        {[1, 2, 3, 4].map(i => <Skeleton key={i} className="h-[120px] rounded-xl" />)}
      </div>
      <div className="grid gap-6 grid-cols-1 lg:grid-cols-2">
        <Skeleton className="h-[300px] rounded-xl" />
        <Skeleton className="h-[300px] rounded-xl" />
      </div>
    </div>
  );
}

export default function Dashboard() {
  const { selectedSiteId } = useSiteContext();
  const { data, loading, error, reload } = useApiResource<DashboardApiResponse>(
    selectedSiteId ? `/api/dashboard?site_id=${selectedSiteId}` : null,
    signal => fetchJson(`/api/dashboard?site_id=${selectedSiteId}&t=${Date.now()}`, { signal }, 'Gagal memuat dashboard'),
  );

  if (error) return <div className="p-6"><ErrorState message={error} onRetry={reload} /></div>;
  if (loading) return <DashboardSkeleton />;
  if (!selectedSiteId) return <EmptyState title="Dashboard Analitik" description="Pilih salah satu website dari menu dropdown di kanan atas untuk memantau ringkasan performa dan otomatisasi postingan Anda." />;

  const { stats, next_post_time, logs, insights, performance } = data || {};

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-primary to-indigo-600 dark:from-primary dark:to-indigo-400 bg-clip-text text-transparent">
          Dashboard
        </h1>
        <p className="text-muted-foreground mt-1">
          Sistem analitik cerdas penerbitan otomatis WordPress & media sosial Anda.
        </p>
      </div>

      <KpiCards stats={stats} nextPostTime={next_post_time} />

      <div className="grid gap-6 md:grid-cols-2">
        <InsightsCard insights={insights} />
        <RecentActivityCard logs={logs} />
      </div>

      {performance && performance.length > 0 && <EngagementChart performance={performance} />}

      <CategoryPerformanceTable performance={performance} />
    </div>
  );
}
