import type { ReactNode } from 'react';
import { BarChart, MessageCircle, FileText, Video, ShieldCheck, ExternalLink } from 'lucide-react';
import type { ResearchStats } from '@/lib/types';

const SOURCE_STATUS: Record<string, { label: string; className: string }> = {
  real: { label: 'Data nyata', className: 'border-emerald-200 bg-emerald-50 text-emerald-700' },
  partial: { label: 'Sebagian', className: 'border-blue-200 bg-blue-50 text-blue-700' },
  fallback: { label: 'Cadangan (fallback)', className: 'border-amber-200 bg-amber-50 text-amber-700' },
  unavailable: { label: 'Tidak tersedia', className: 'border-border bg-muted/40 text-muted-foreground' },
};
const UNKNOWN_SOURCE_CLASS = 'border-border bg-background text-muted-foreground';

const SOURCE_LABEL: Record<string, string> = {
  google_trends: 'Google Trends',
  trend_analysis: 'Analisis tren',
  google_autocomplete: 'Google Autocomplete',
  google_related_queries: 'Kueri terkait Google',
  related_questions: 'Pertanyaan terkait',
  search_console: 'Search Console',
  competitors: 'Kompetitor',
  social: 'Sosial',
  news: 'Berita',
  wikipedia: 'Wikipedia',
  youtube: 'YouTube',
};

/** Source entries worth a chip: trend_analysis repeats google_trends when both exist. */
function sourceEntries(metadata: ResearchStats['source_metadata']) {
  return Object.entries(metadata || {}).filter(([provider, meta]) => (
    meta && typeof meta === 'object' && 'status' in meta
    && !(provider === 'trend_analysis' && metadata.google_trends)
  ));
}

function SectionTitle({ icon, className, children }: { icon: ReactNode; className: string; children: ReactNode }) {
  return (
    <div className={`flex items-center gap-2 font-semibold ${className}`}>
      {icon}
      <span>{children}</span>
    </div>
  );
}

function KeywordsSection({ keywords }: { keywords: ResearchStats['keywords'] }) {
  return (
    <div className="p-6 space-y-4 bg-primary/5">
      <SectionTitle icon={<BarChart className="h-4 w-4" />} className="text-primary">Kata Kunci Teratas</SectionTitle>
      <div className="flex flex-wrap gap-2">
        {keywords && keywords.length > 0 ? (
          keywords.map((kw, i) => {
            const text = typeof kw === 'string' ? kw : kw.keyword;
            const impressions = typeof kw === 'string' ? null : kw.impressions;
            return (
              <span
                key={i}
                title={impressions ? `${impressions.toLocaleString('id-ID')} impresi di Search Console` : undefined}
                className="text-xs px-2.5 py-1 bg-background border shadow-sm rounded-full text-foreground/80 hover:text-foreground transition-colors inline-flex items-center gap-1.5"
              >
                {text}
                {impressions ? (
                  <span className="text-[10px] font-medium text-primary">
                    {impressions.toLocaleString('id-ID')}
                  </span>
                ) : null}
              </span>
            );
          })
        ) : (
          <span className="text-xs text-muted-foreground italic">Tidak ada kata kunci</span>
        )}
      </div>
    </div>
  );
}

function SocialSection({ insights }: { insights: ResearchStats['social_insights'] }) {
  return (
    <div className="p-6 space-y-4">
      <SectionTitle icon={<MessageCircle className="h-4 w-4" />} className="text-orange-600">Social Listening</SectionTitle>
      <ul className="space-y-3">
        {insights && insights.length > 0 ? (
          insights.map((item, i) => {
            const text = typeof item === 'string' ? item : item.text;
            const url = typeof item === 'string' ? undefined : item.url;
            return (
              <li key={i} className="text-sm text-muted-foreground leading-snug flex gap-2">
                <span className="text-orange-500 font-bold">•</span>
                {url ? <a href={url} target="_blank" rel="noreferrer" className="hover:underline">{text}</a> : text}
              </li>
            );
          })
        ) : (
          <li className="text-sm text-muted-foreground italic">Belum ada diskusi sosial terbaru</li>
        )}
      </ul>
    </div>
  );
}

function CompetitorsSection({ outlines }: { outlines: ResearchStats['competitor_outlines'] }) {
  return (
    <div className="p-6 space-y-4">
      <SectionTitle icon={<FileText className="h-4 w-4" />} className="text-blue-600">Kompetitor Teratas</SectionTitle>
      <div className="space-y-4">
        {outlines && outlines.length > 0 ? (
          outlines.map((comp, i) => (
            <div key={i} className="space-y-1">
              <a href={comp.url} target="_blank" rel="noreferrer" className="text-sm font-medium hover:underline text-foreground line-clamp-1">
                {comp.title}
              </a>
              <div className="flex flex-wrap gap-1">
                {comp.headers && comp.headers.slice(0, 3).map((h, j) => (
                  <span key={j} className="text-[10px] px-1.5 py-0.5 bg-muted text-muted-foreground rounded truncate max-w-[120px]">
                    {h}
                  </span>
                ))}
              </div>
            </div>
          ))
        ) : (
          <div className="text-sm text-muted-foreground italic">Tidak ada data kompetitor</div>
        )}
      </div>
    </div>
  );
}

function VideoSection({ videos }: { videos: ResearchStats['youtube_insights'] }) {
  return (
    <div className="p-6 space-y-4 bg-red-50/30 dark:bg-red-950/10">
      <SectionTitle icon={<Video className="h-4 w-4" />} className="text-red-600">Insight Video</SectionTitle>
      <div className="space-y-3">
        {videos && videos.length > 0 ? (
          videos.map((yt, i) => (
            <div key={i} className="text-sm">
              {yt.url ? (
                <a href={yt.url} target="_blank" rel="noreferrer" className="font-medium line-clamp-1 mb-1 hover:underline">{yt.title}</a>
              ) : <p className="font-medium line-clamp-1 mb-1">{yt.title}</p>}
              {yt.transcript_available && yt.snippets ? (
                <p className="text-xs text-muted-foreground line-clamp-3 bg-white/50 p-2 rounded border border-red-100">“{yt.snippets}”</p>
              ) : (
                <p className="text-xs text-muted-foreground italic">Video ditemukan, tetapi transkrip tidak tersedia dan tidak dibuat-buat.</p>
              )}
            </div>
          ))
        ) : (
          <div className="text-sm text-muted-foreground italic">Tidak ada transkrip video</div>
        )}
      </div>
    </div>
  );
}

function SourceTransparency({ stats }: { stats: ResearchStats }) {
  return (
    <div className="border-t p-6 space-y-5 bg-muted/10">
      <div className="flex items-center gap-2 font-semibold">
        <ShieldCheck className="h-4 w-4 text-emerald-600" />
        Transparansi Sumber
      </div>
      <div className="flex flex-wrap gap-2">
        {sourceEntries(stats.source_metadata).map(([provider, meta]) => {
          const status = meta.status ? SOURCE_STATUS[meta.status] : undefined;
          return (
            <span
              key={provider}
              title={meta.reason ? `Alasan: ${meta.reason}` : undefined}
              className={`rounded-full border px-2.5 py-1 text-xs ${status?.className ?? UNKNOWN_SOURCE_CLASS}`}
            >
              {SOURCE_LABEL[provider] ?? provider.replaceAll('_', ' ')}: {status?.label ?? meta.status ?? 'Tidak diketahui'}
              {typeof meta.count === 'number' ? ` (${meta.count.toLocaleString('id-ID')})` : ''}
            </span>
          );
        })}
      </div>

      {stats.long_tail_keywords?.length > 0 && (
        <div>
          <p className="mb-2 text-sm font-semibold">Peluang long-tail</p>
          <div className="flex flex-wrap gap-2">
            {stats.long_tail_keywords.slice(0, 10).map((keyword, index) => (
              <span key={index} className="rounded-md border bg-background px-2 py-1 text-xs text-muted-foreground">{keyword}</span>
            ))}
          </div>
        </div>
      )}

      {stats.news_insights?.length > 0 && (
        <div>
          <p className="mb-2 text-sm font-semibold">Berita pendukung terbaru</p>
          <div className="grid gap-2 md:grid-cols-2">
            {stats.news_insights.map((news, index) => (
              <div key={index} className="rounded-md border bg-background p-3 text-sm">
                {news.url ? (
                  <a href={news.url} target="_blank" rel="noreferrer" className="font-medium hover:underline">
                    {news.title} <ExternalLink className="inline h-3 w-3" />
                  </a>
                ) : <p className="font-medium">{news.title}</p>}
                {news.source && <p className="mt-1 text-xs text-muted-foreground">{news.source}</p>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** Body of a researched category card: keyword, social, competitor, video and source panels. */
export function ResearchInsights({ stats }: { stats: ResearchStats }) {
  return (
    <>
      <div className="grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x border-b">
        <KeywordsSection keywords={stats.keywords} />
        <SocialSection insights={stats.social_insights} />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x">
        <CompetitorsSection outlines={stats.competitor_outlines} />
        <VideoSection videos={stats.youtube_insights} />
      </div>
      <SourceTransparency stats={stats} />
    </>
  );
}
