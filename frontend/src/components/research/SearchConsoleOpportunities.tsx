import { SearchCheck, MousePointerClick, AlertTriangle } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import type { SearchConsoleSummary, SearchOpportunity } from '@/lib/types';

const TYPE_STYLES: Record<SearchOpportunity['type'], { label: string; className: string }> = {
  quick_win: { label: 'Quick win', className: 'bg-emerald-100 text-emerald-700' },
  low_ctr: { label: 'CTR rendah', className: 'bg-blue-100 text-blue-700' },
  declining: { label: 'Menurun', className: 'bg-red-100 text-red-700' },
};

/** Short badge text per recommended action; the full advice is action_label. */
const ACTION_STYLES: Record<string, { label: string; className: string }> = {
  new_article: { label: 'Tulis artikel baru', className: 'border-indigo-200 bg-indigo-50 text-indigo-700' },
  rewrite_meta: { label: 'Perbarui title & meta', className: 'border-amber-200 bg-amber-50 text-amber-800' },
  refresh_content: { label: 'Perbarui halaman', className: 'border-sky-200 bg-sky-50 text-sky-700' },
};

const INTENT_LABEL: Record<string, string> = {
  informational: 'Informasional',
  commercial: 'Komersial',
  transactional: 'Transaksional',
  navigational: 'Navigasional',
};

const formatCount = (value: number) => (Number(value) || 0).toLocaleString('id-ID');
const formatDecimal = (value: number) => (Number(value) || 0).toLocaleString('id-ID', { maximumFractionDigits: 1 });

function SyncError({ message }: { message: string }) {
  return (
    <div role="alert" className="flex items-start gap-3 border-b border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <span>Data Search Console tidak dapat dimuat: {message}</span>
    </div>
  );
}

export function SearchConsoleOpportunities({ summary }: { summary: SearchConsoleSummary }) {
  return (
    <Card className="overflow-hidden border-emerald-200/70 shadow-md">
      <CardHeader className="border-b bg-gradient-to-r from-emerald-50 dark:from-emerald-950/40 to-background">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-xl"><SearchCheck className="h-5 w-5 text-emerald-600" /> Peluang Search Console</CardTitle>
            <CardDescription className="mt-1">Quick win dari performa pencarian aktual website, bukan estimasi keyword eksternal.</CardDescription>
          </div>
          <div className="text-right text-xs text-muted-foreground">
            <p>{summary.property_url}</p>
            {summary.last_synced_at && <p>Sinkron: {new Date(summary.last_synced_at).toLocaleString('id-ID')}</p>}
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {summary.error && <SyncError message={summary.error} />}
        {summary.opportunities?.length ? (
          <div className="divide-y">
            {summary.opportunities.slice(0, 8).map((item, index) => {
              const type = TYPE_STYLES[item.type] ?? { label: String(item.type).replace('_', ' '), className: TYPE_STYLES.declining.className };
              const action = item.action ? ACTION_STYLES[item.action] : undefined;
              const actionBadge = action?.label ?? item.action_label;
              return (
                <div key={`${item.query}-${item.page}-${index}`} className="grid gap-3 p-4 hover:bg-muted/20 md:grid-cols-[1fr_auto]">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${type.className}`}>
                        {type.label}
                      </span>
                      {actionBadge && (
                        <span
                          title={item.action_label || undefined}
                          className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${action?.className ?? 'border-border bg-background text-foreground'}`}
                        >
                          {actionBadge}
                        </span>
                      )}
                      <span className="rounded-full border px-2 py-0.5 text-xs font-semibold">Peluang {item.opportunity_score}/100</span>
                      {item.intent && (
                        <span className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
                          Intent: {INTENT_LABEL[item.intent] ?? item.intent}
                        </span>
                      )}
                    </div>
                    <p className="mt-2 font-semibold text-foreground">{item.query}</p>
                    <a href={item.page} target="_blank" rel="noreferrer" className="mt-1 block truncate text-xs text-muted-foreground hover:underline">{item.page}</a>
                    {item.action_label && <p className="mt-2 text-xs font-medium text-foreground/80">Rekomendasi: {item.action_label}</p>}
                    <p className="mt-2 text-xs text-muted-foreground">{item.rationale}</p>
                  </div>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs md:min-w-[230px]">
                    <span className="text-muted-foreground">Impresi</span><strong>{formatCount(item.impressions)}</strong>
                    <span className="text-muted-foreground">Klik</span><strong>{formatCount(item.clicks)}</strong>
                    <span className="text-muted-foreground">CTR</span><strong>{formatDecimal(item.ctr)}%</strong>
                    <span className="text-muted-foreground">Posisi</span><strong>{formatDecimal(item.position)}</strong>
                  </div>
                </div>
              );
            })}
          </div>
        ) : !summary.error && (
          <div className="flex items-center gap-3 p-6 text-sm text-muted-foreground">
            <MousePointerClick className="h-5 w-5" /> Belum ada peluang. Jalankan sinkronisasi dari konfigurasi Website.
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function ConnectSearchConsolePrompt() {
  const navigate = useNavigate();
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-dashed bg-muted/10 p-4">
      <div>
        <p className="font-semibold">Aktifkan SEO intelligence dari data Anda sendiri</p>
        <p className="text-sm text-muted-foreground">Hubungkan Google Search Console untuk menemukan keyword posisi 4–20, CTR rendah, dan penurunan klik.</p>
      </div>
      <Button variant="outline" onClick={() => navigate('/sites')}><SearchCheck className="mr-2 h-4 w-4" /> Hubungkan Search Console</Button>
    </div>
  );
}
