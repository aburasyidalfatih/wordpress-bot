import { TrendingUp, MessageSquare } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import type { CategoryPerformance } from '@/lib/types';

const CHART_HEIGHT = 160;
const CHART_WIDTH = 600;

function chartGeometry(performance: CategoryPerformance[]) {
  const maxVal = Math.max(...performance.map(c => c.avg_engagement || 1.0), 2.0);
  const len = performance.length;
  const points = performance.map((cat, idx) => {
    const x = len > 1 ? (idx / (len - 1)) * (CHART_WIDTH - 80) + 40 : CHART_WIDTH / 2;
    const y = CHART_HEIGHT - ((cat.avg_engagement || 0) / maxVal) * (CHART_HEIGHT - 60) - 30;
    return { x, y, name: cat.category, val: cat.avg_engagement || 0 };
  });
  const polyline = points.map(p => `${p.x},${p.y}`).join(' ');
  const area = `${points[0].x},${CHART_HEIGHT - 10} ${polyline} ${points[points.length - 1].x},${CHART_HEIGHT - 10}`;
  return { points, polyline, area };
}

/** SVG line chart of the average engagement per category. Needs at least one category. */
export function EngagementChart({ performance }: { performance: CategoryPerformance[] }) {
  const { points, polyline, area } = chartGeometry(performance);
  return (
    <Card className="border-border/50 shadow-md overflow-hidden bg-gradient-to-br from-card to-indigo-500/[0.02]">
      <CardHeader>
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
          <div>
            <CardTitle className="flex items-center gap-2 text-xl">
              <TrendingUp className="h-5 w-5 text-indigo-500" />
              <span>Tren Engagement Kategori</span>
            </CardTitle>
            <CardDescription>Visualisasi tingkat keterlibatan pengunjung berdasarkan rata-rata interaksi.</CardDescription>
          </div>
          <div className="flex gap-4 text-xs font-medium text-muted-foreground bg-background/50 border rounded-lg p-2">
            <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-indigo-500" /> Rata-rata Skor Engagement</span>
          </div>
        </div>
      </CardHeader>
      <CardContent className="pt-2 px-6 pb-6">
        <div className="w-full overflow-hidden">
          <div className="w-full h-[180px] relative">
            <svg className="w-full h-full overflow-visible" viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`} preserveAspectRatio="none">
              {/* Grid Lines */}
              {[30, 70, 110].map(y => (
                <line key={y} x1="40" y1={y} x2={CHART_WIDTH - 40} y2={y} stroke="var(--border)" strokeDasharray="3 3" opacity="0.5" />
              ))}
              <line x1="40" y1={CHART_HEIGHT - 30} x2={CHART_WIDTH - 40} y2={CHART_HEIGHT - 30} stroke="var(--border)" opacity="0.8" />

              {/* Area fill under the path */}
              <polygon points={area} fill="url(#chartGrad)" opacity="0.15" />

              {/* The trend line */}
              <polyline
                fill="none"
                stroke="url(#lineGrad)"
                strokeWidth="3.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                points={polyline}
                className="animate-chart"
              />

              {/* Data Points */}
              {points.map((pt, idx) => (
                <g key={idx} className="group/pt cursor-pointer">
                  <circle
                    cx={pt.x}
                    cy={pt.y}
                    r="6"
                    className="fill-background stroke-indigo-500 stroke-[3px] transition-all group-hover/pt:r-8 group-hover/pt:stroke-[4px]"
                  />
                  <circle
                    cx={pt.x}
                    cy={pt.y}
                    r="12"
                    className="fill-indigo-500/10 opacity-0 group-hover/pt:opacity-100 transition-opacity"
                  />
                  {/* Tooltip bubble on hover */}
                  <text
                    x={pt.x}
                    y={pt.y - 14}
                    textAnchor="middle"
                    className="text-[10px] font-bold fill-indigo-600 dark:fill-indigo-400 opacity-0 group-hover/pt:opacity-100 transition-opacity pointer-events-none"
                  >
                    {pt.val.toFixed(1)}
                  </text>
                </g>
              ))}

              {/* X-axis Labels */}
              {points.map((pt, idx) => (
                <text
                  key={idx}
                  x={pt.x}
                  y={CHART_HEIGHT - 10}
                  textAnchor="middle"
                  className="text-[10px] font-semibold fill-muted-foreground select-none"
                >
                  {pt.name.length > 12 ? `${pt.name.slice(0, 10)}...` : pt.name}
                </text>
              ))}

              {/* Gradients */}
              <defs>
                <linearGradient id="lineGrad" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%" stopColor="var(--primary)" />
                  <stop offset="100%" stopColor="#4f46e5" />
                </linearGradient>
                <linearGradient id="chartGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--primary)" />
                  <stop offset="100%" stopColor="var(--primary)" stopOpacity="0" />
                </linearGradient>
              </defs>
            </svg>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

const TH = 'h-12 px-6 align-middle font-semibold text-muted-foreground';
const TD = 'px-6 py-4 align-middle text-center font-medium text-foreground/80';

export function CategoryPerformanceTable({ performance }: { performance?: CategoryPerformance[] }) {
  return (
    <Card className="border-border/50 shadow-md overflow-hidden">
      <CardHeader>
        <CardTitle>Performa Kategori Detail</CardTitle>
        <CardDescription>Rincian performa postingan dan total keterlibatan per kategori.</CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        {performance && performance.length > 0 ? (
          <div className="relative w-full overflow-auto">
            <table className="w-full caption-bottom text-sm">
              <thead>
                <tr className="border-b bg-muted/30 select-none">
                  <th className={`${TH} text-left`}>Kategori</th>
                  <th className={`${TH} text-center`}>Total Artikel</th>
                  <th className={`${TH} text-center`}>Total Dilihat</th>
                  <th className={`${TH} text-center`}>Total Komentar</th>
                  <th className={`${TH} text-right`}>Rata-rata Engagement</th>
                </tr>
              </thead>
              <tbody className="divide-y border-b divide-border/40">
                {performance.map((cat, idx) => (
                  <tr key={idx} className="hover:bg-secondary/40 transition-colors">
                    <td className="px-6 py-4 align-middle font-bold text-foreground/95 capitalize">{cat.category}</td>
                    <td className={TD}>{cat.total_posts}</td>
                    <td className={TD}>{cat.total_views}</td>
                    <td className={TD}>{cat.total_comments}</td>
                    <td className="px-6 py-4 align-middle text-right font-bold text-indigo-600 dark:text-indigo-400">
                      {cat.avg_engagement?.toFixed(1)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-center py-12 text-muted-foreground flex flex-col items-center justify-center">
            <MessageSquare className="h-12 w-12 text-muted-foreground/30 mb-3" />
            <p className="text-sm font-medium">Belum ada data performa kategori.</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
