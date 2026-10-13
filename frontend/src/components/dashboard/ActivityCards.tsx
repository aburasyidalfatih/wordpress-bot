import { Clock, BarChart2, Lightbulb, Sparkles } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import type { DashboardInsightsData, DashboardLogEntry } from '@/lib/types';

const RECOMMENDATION_LABELS: Record<string, string> = {
  increase_frequency: 'tambah frekuensi',
  improve_content: 'tingkatkan konten',
};

export function InsightsCard({ insights }: { insights?: DashboardInsightsData }) {
  const recommendations = insights?.status === 'success' ? insights.recommendations ?? [] : [];
  return (
    <Card className="border-border/50 shadow-md flex flex-col justify-between">
      <CardHeader>
        <CardTitle className="flex items-center gap-2.5 text-xl">
          <Lightbulb className="h-5 w-5 text-amber-500 animate-pulse" />
          <span>AI Insights & Rekomendasi</span>
        </CardTitle>
        <CardDescription>Analisis performa cerdas berbasis Machine Learning.</CardDescription>
      </CardHeader>
      <CardContent className="flex-1">
        {recommendations.length > 0 ? (
          <div className="space-y-4">
            {recommendations.map((rec, idx) => {
              const positive = rec.type === 'increase_frequency';
              return (
                <div
                  key={idx}
                  className={`p-4 rounded-xl border flex gap-3 transition-all hover:scale-[1.01] ${
                    positive
                      ? 'bg-green-500/5 border-green-500/20 text-green-950 dark:text-green-200'
                      : 'bg-amber-500/5 border-amber-500/20 text-amber-950 dark:text-amber-200'
                  }`}
                >
                  <Sparkles className={`h-5 w-5 shrink-0 mt-0.5 ${positive ? 'text-green-500' : 'text-amber-500'}`} />
                  <div>
                    <h4 className="font-bold text-sm flex items-center gap-2">
                      <span>{rec.category}</span>
                      <span className="text-[10px] font-semibold uppercase tracking-wider opacity-70 px-2 py-0.5 rounded bg-background/50 border">
                        {RECOMMENDATION_LABELS[rec.type] ?? rec.type.replace('_', ' ')}
                      </span>
                    </h4>
                    <p className="text-sm mt-1 text-foreground/80">{rec.action}</p>
                    <p className="text-xs mt-2 opacity-65 italic font-medium">{rec.reason}</p>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="text-center py-12 text-muted-foreground flex flex-col items-center justify-center">
            <BarChart2 className="h-12 w-12 text-muted-foreground/30 mb-3" />
            <p className="text-sm font-medium">{insights?.message || 'Data belum mencukupi untuk menghasilkan AI insights.'}</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function statusBadge(success: DashboardLogEntry['success']) {
  if (success === 'pending') {
    return { label: 'Proses / Menunggu', className: 'bg-amber-500/10 border-amber-500/20 text-amber-700 dark:text-amber-400 animate-pulse' };
  }
  return success
    ? { label: 'Berhasil', className: 'bg-green-500/10 border-green-500/20 text-green-700 dark:text-green-400' }
    : { label: 'Gagal', className: 'bg-red-500/10 border-red-500/20 text-red-700 dark:text-red-400' };
}

export function RecentActivityCard({ logs }: { logs?: DashboardLogEntry[] }) {
  return (
    <Card className="border-border/50 shadow-md">
      <CardHeader>
        <CardTitle className="text-xl">Aktivitas Terkini</CardTitle>
        <CardDescription>Catatan publikasi artikel otomatis terakhir.</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {logs && logs.length > 0 ? logs.slice(0, 5).map((log, i) => {
            const badge = statusBadge(log.success);
            return (
              <div key={i} className="flex justify-between items-start pb-4 border-b last:border-0 last:pb-0 last:border-none group">
                <div className="space-y-1 pr-4">
                  <p className="text-sm font-semibold text-foreground/90 group-hover:text-primary transition-colors leading-tight line-clamp-2">
                    {log.title}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    📂 {log.category} • {new Date(log.timestamp).toLocaleString()}
                  </p>
                  {log.success === false && log.result && (
                    <p className="text-xs text-destructive break-words">{log.result}</p>
                  )}
                </div>
                <span className={`px-2.5 py-1 rounded-full text-xs font-semibold shrink-0 shadow-sm border ${badge.className}`}>
                  {badge.label}
                </span>
              </div>
            );
          }) : (
            <div className="text-center py-12 text-muted-foreground flex flex-col items-center justify-center">
              <Clock className="h-12 w-12 text-muted-foreground/30 mb-3" />
              <p className="text-sm font-medium">Belum ada aktivitas publikasi.</p>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
