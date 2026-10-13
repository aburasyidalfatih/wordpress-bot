import type { ReactNode } from 'react';
import { FileText, CheckCircle, Clock, AlertCircle } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { DashboardApiResponse } from '@/lib/types';

interface KpiCardProps {
  title: string;
  icon: ReactNode;
  /** Classes for the card gradient and the icon badge. */
  gradient: string;
  iconClass: string;
  value: ReactNode;
  valueClass: string;
  note: string;
  noteClass?: string;
}

function KpiCard({ title, icon, gradient, iconClass, value, valueClass, note, noteClass = 'mt-1' }: KpiCardProps) {
  return (
    <Card className={`overflow-hidden border-border/50 shadow-md hover:shadow-xl hover:scale-[1.02] transition-all duration-300 bg-gradient-to-br from-card ${gradient}`}>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-semibold tracking-wide uppercase text-muted-foreground">{title}</CardTitle>
        <div className={`p-2 rounded-lg ${iconClass}`}>{icon}</div>
      </CardHeader>
      <CardContent className="pt-2">
        <div className={valueClass}>{value}</div>
        <p className={`text-xs text-muted-foreground ${noteClass}`}>{note}</p>
      </CardContent>
    </Card>
  );
}

export function KpiCards({ stats, nextPostTime }: { stats: DashboardApiResponse['stats']; nextPostTime?: string }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
      <KpiCard
        title="Total Artikel"
        icon={<FileText className="h-5 w-5" />}
        gradient="to-primary/5"
        iconClass="bg-primary/10 text-primary"
        value={stats?.total_posts || 0}
        valueClass="text-3xl font-extrabold tracking-tight"
        note="Artikel berhasil dipublikasikan"
      />
      <KpiCard
        title="Tingkat Keberhasilan"
        icon={<CheckCircle className="h-5 w-5" />}
        gradient="to-green-500/5"
        iconClass="bg-green-500/10 text-green-600"
        value={`${stats?.success_rate || 0}%`}
        valueClass="text-3xl font-extrabold tracking-tight text-green-600 dark:text-green-400"
        note="Rasio keberhasilan bot"
      />
      <KpiCard
        title="Artikel Gagal"
        icon={<AlertCircle className="h-5 w-5" />}
        gradient="to-red-500/5"
        iconClass="bg-red-500/10 text-red-500"
        value={stats?.failed_posts || 0}
        valueClass="text-3xl font-extrabold tracking-tight text-red-600 dark:text-red-400"
        note="Perlu tindakan/perbaikan"
      />
      <KpiCard
        title="Jadwal Berikutnya"
        icon={<Clock className="h-5 w-5" />}
        gradient="to-indigo-500/5"
        iconClass="bg-indigo-500/10 text-indigo-500"
        value={nextPostTime ? new Date(nextPostTime).toLocaleString() : 'Belum dijadwalkan'}
        valueClass="text-lg font-bold truncate tracking-tight text-indigo-600 dark:text-indigo-400"
        note="Jadwal auto-post berikutnya"
        noteClass="mt-2"
      />
    </div>
  );
}
