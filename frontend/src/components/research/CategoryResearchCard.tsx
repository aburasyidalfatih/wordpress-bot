import { useId } from 'react';
import { RefreshCw, TrendingUp, Sparkles, ShieldCheck, AlertTriangle, Clock } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import type { ResearchStats, SiteCategory } from '@/lib/types';
import { ResearchInsights } from './ResearchInsights';

const CONFIDENCE_LABEL: Record<string, string> = {
  high: 'Tinggi', medium: 'Sedang', low: 'Rendah',
  insufficient: 'Tidak mencukupi', unknown: 'Data lama',
};

const CONFIDENCE_CLASS: Record<string, string> = {
  high: 'bg-emerald-100 text-emerald-700 border-emerald-200',
  medium: 'bg-blue-100 text-blue-700 border-blue-200',
  low: 'bg-amber-100 text-amber-700 border-amber-200',
  insufficient: 'bg-red-100 text-red-700 border-red-200',
  unknown: 'bg-muted text-muted-foreground border-border',
};

interface CategoryActions {
  /** True while any research/bulk job runs. */
  researching: boolean;
  /** True while research for this particular category runs. */
  isResearchingThis: boolean;
  onResearch: () => void;
}

/** Card for a target category that has no research yet. */
export function EmptyCategoryCard({ category, researching, isResearchingThis, onResearch }: CategoryActions & { category: SiteCategory }) {
  return (
    <Card className="overflow-hidden border-dashed border-2 border-border bg-muted/15 p-6 flex flex-col justify-between min-h-[220px] shadow-sm hover:border-primary/50 transition-all duration-300">
      <div className="space-y-2">
        <h3 className="text-xl font-bold capitalize text-muted-foreground/90">{category.name}</h3>
        {category.description && (
          <p className="text-xs text-muted-foreground/80 line-clamp-2">{category.description}</p>
        )}
        <p className="text-sm text-muted-foreground leading-relaxed">
          Belum ada riset untuk kategori ini. Mulai riset kategori ini secara terpisah untuk menemukan tren kata kunci kompetitor, tren sosial, dan video YouTube terpopuler.
        </p>
      </div>
      <div className="pt-4 flex justify-start">
        <Button
          onClick={onResearch}
          disabled={researching}
          className="gap-2 bg-primary hover:bg-primary/90 text-primary-foreground shadow-md transition-all font-semibold"
        >
          <RefreshCw className={`h-4 w-4 ${isResearchingThis ? 'animate-spin' : ''}`} />
          Mulai Riset Kategori (1 Kredit)
        </Button>
      </div>
    </Card>
  );
}

/** Every caveat that applies to the research; age and missing evidence can both apply. */
function researchWarnings(stats: ResearchStats): string[] {
  const warnings: string[] = [];
  if (stats.is_stale) warnings.push('Data ini berusia lebih dari 7 hari. Riset ulang sebelum membuat keputusan konten.');
  else if (stats.confidence_level === 'unknown') warnings.push('Data ini dibuat sebelum sistem quality scoring tersedia. Riset ulang untuk hasil terverifikasi.');
  if (stats.fallback_warnings) {
    // Names the writer evidence that is missing; optional sources are shown separately.
    warnings.push(...stats.fallback_warnings);
  } else if (stats.is_fallback) {
    warnings.push('Sebagian data memakai fallback dan tidak dianggap sebagai bukti sumber nyata.');
  }
  return warnings;
}

/** "Skor Tren (emergency fund):" when the score was measured for the shorter head term. */
function trendLabel(stats: ResearchStats): string {
  const term = stats.source_metadata?.google_trends?.trend_term;
  return term ? `Skor Tren (${term}):` : 'Skor Tren:';
}

interface CategoryResearchCardProps extends CategoryActions {
  name: string;
  stats: ResearchStats;
  isGenerating: boolean;
  /** Another title request (single or bulk) is running. */
  titlesBusy: boolean;
  /** Why titles cannot be generated from this research; null when they can. */
  titleBlockReason: string | null;
  onGenerateTitles: () => void;
}

/** Card with the research results of one category. */
export function CategoryResearchCard({
  name, stats, researching, isResearchingThis, onResearch, isGenerating, titlesBusy, titleBlockReason, onGenerateTitles,
}: CategoryResearchCardProps) {
  const trendScore = stats.trend_score || 0;
  const qualityScore = Math.min(100, Math.max(0, stats.quality_score || 0));
  const warnings = researchWarnings(stats);
  const titleReasonId = useId();

  return (
    <Card className="overflow-hidden border-border/50 shadow-md hover:shadow-xl transition-all duration-300 group">
      <CardHeader className="bg-gradient-to-r from-muted/50 to-muted/10 border-b pb-6">
        <div className="flex justify-between items-start">
          <div>
            <CardTitle className="text-2xl capitalize mb-2 group-hover:text-primary transition-colors">{name}</CardTitle>
            <CardDescription className="flex flex-wrap items-center gap-2">
              <TrendingUp className="h-4 w-4 text-green-500" />
              {trendLabel(stats)} <span className="font-bold text-foreground">{trendScore > 0 ? `${trendScore}/100` : 'Tidak tersedia'}</span>
              <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold ${CONFIDENCE_CLASS[stats.confidence_level] || CONFIDENCE_CLASS.unknown}`}>
                <ShieldCheck className="h-3 w-3" />
                Keyakinan {CONFIDENCE_LABEL[stats.confidence_level] || 'Data lama'} · {qualityScore}/100
              </span>
            </CardDescription>
          </div>
          <div className="flex flex-col items-end gap-2">
            <span className="text-xs text-muted-foreground bg-background/80 backdrop-blur-sm px-2.5 py-1 rounded-full border shadow-sm">
              <Clock className="mr-1 inline h-3 w-3" />{stats.created_at}
            </span>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={onResearch}
                disabled={researching}
                className="gap-1 border-primary/30 text-primary hover:bg-primary/5 hover:text-primary bg-background/50 font-semibold"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${isResearchingThis ? 'animate-spin' : ''}`} />
                Riset Ulang (1 Kredit)
              </Button>
              {/* Disabled buttons get no hover events, so the wrapper carries the tooltip. */}
              <span title={titleBlockReason ?? undefined} className="inline-flex">
                <Button
                  size="sm"
                  onClick={onGenerateTitles}
                  disabled={isGenerating || titlesBusy || !!titleBlockReason}
                  aria-describedby={titleBlockReason ? titleReasonId : undefined}
                  className="bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm gap-1"
                >
                  <Sparkles className={`h-3.5 w-3.5 ${isGenerating ? 'animate-pulse' : ''}`} />
                  {isGenerating ? 'Memproses...' : 'Buat Judul AI'}
                </Button>
              </span>
            </div>
          </div>
        </div>
        {titleBlockReason && (
          <p id={titleReasonId} className="mt-3 text-xs text-muted-foreground">
            Judul AI belum bisa dibuat: {titleBlockReason}
          </p>
        )}
        {warnings.map(warning => (
          <div key={warning} className="mt-4 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{warning}</span>
          </div>
        ))}
        <div
          role="meter"
          aria-label="Skor kualitas riset"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={qualityScore}
          aria-valuetext={`${qualityScore} dari 100`}
          className="w-full bg-secondary rounded-full h-2 mt-4 overflow-hidden"
        >
          <div className="bg-primary h-2 rounded-full transition-all" style={{ width: `${qualityScore}%` }} />
        </div>
      </CardHeader>

      <CardContent className="p-0">
        <ResearchInsights stats={stats} />
      </CardContent>
    </Card>
  );
}
