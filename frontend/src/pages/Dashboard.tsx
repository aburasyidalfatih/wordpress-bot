import { apiFetch } from '../lib/api';
import { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { FileText, CheckCircle, Clock, BarChart2, AlertCircle, Lightbulb, TrendingUp, Sparkles, MessageSquare } from 'lucide-react';

import { useSiteContext } from '@/contexts/SiteContext';

export default function Dashboard() {
  const { selectedSiteId } = useSiteContext();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!selectedSiteId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    apiFetch(`/api/dashboard?site_id=${selectedSiteId}`)
      .then(res => res.json())
      .then(d => {
        setData(d);
        setLoading(false);
      });
  }, [selectedSiteId]);

  if (loading) return (
    <div className="p-8 flex items-center justify-center min-h-[400px]">
      <div className="flex flex-col items-center gap-4 text-muted-foreground">
        <Clock className="h-8 w-8 animate-spin text-primary" />
        Loading intelligence dashboard...
      </div>
    </div>
  );

  if (!selectedSiteId) return <div className="p-8 text-center text-muted-foreground mt-20">Please select a website from the top bar to view its dashboard.</div>;

  const { stats, next_post_time, logs, insights, performance } = data || {};

  // Calculate SVG Chart coordinates if performance data exists
  const hasPerfData = performance && performance.length > 0;
  let chartPoints: any[] = [];
  let polylinePoints = "";
  let areaPoints = "";
  const chartHeight = 160;
  const chartWidth = 600;

  if (hasPerfData) {
    const maxVal = Math.max(...performance.map((c: any) => c.avg_engagement || 1.0), 2.0);
    const len = performance.length;
    chartPoints = performance.map((cat: any, idx: number) => {
      const x = len > 1 ? (idx / (len - 1)) * (chartWidth - 80) + 40 : chartWidth / 2;
      const y = chartHeight - ((cat.avg_engagement || 0) / maxVal) * (chartHeight - 60) - 30;
      return { x, y, name: cat.category, val: cat.avg_engagement || 0 };
    });
    
    polylinePoints = chartPoints.map(p => `${p.x},${p.y}`).join(' ');
    areaPoints = `${chartPoints[0].x},${chartHeight - 10} ` + 
                 polylinePoints + 
                 ` ${chartPoints[chartPoints.length - 1].x},${chartHeight - 10}`;
  }

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      
      {/* Header */}
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-primary to-indigo-600 dark:from-primary dark:to-indigo-400 bg-clip-text text-transparent">
          Dashboard
        </h1>
        <p className="text-muted-foreground mt-1">
          Sistem analitik cerdas penerbitan otomatis WordPress & media sosial Anda.
        </p>
      </div>
      
      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        
        <Card className="overflow-hidden border-border/50 shadow-md hover:shadow-xl hover:scale-[1.02] transition-all duration-300 bg-gradient-to-br from-card to-primary/5">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-semibold tracking-wide uppercase text-muted-foreground">Total Posts</CardTitle>
            <div className="p-2 rounded-lg bg-primary/10 text-primary">
              <FileText className="h-5 w-5" />
            </div>
          </CardHeader>
          <CardContent className="pt-2">
            <div className="text-3xl font-extrabold tracking-tight">{stats?.total_posts || 0}</div>
            <p className="text-xs text-muted-foreground mt-1">Artikel berhasil dipublish</p>
          </CardContent>
        </Card>
        
        <Card className="overflow-hidden border-border/50 shadow-md hover:shadow-xl hover:scale-[1.02] transition-all duration-300 bg-gradient-to-br from-card to-green-500/5">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-semibold tracking-wide uppercase text-muted-foreground">Success Rate</CardTitle>
            <div className="p-2 rounded-lg bg-green-500/10 text-green-600">
              <CheckCircle className="h-5 w-5" />
            </div>
          </CardHeader>
          <CardContent className="pt-2">
            <div className="text-3xl font-extrabold tracking-tight text-green-600 dark:text-green-400">
              {stats?.success_rate || 0}%
            </div>
            <p className="text-xs text-muted-foreground mt-1">Rasio kesuksesan bot</p>
          </CardContent>
        </Card>

        <Card className="overflow-hidden border-border/50 shadow-md hover:shadow-xl hover:scale-[1.02] transition-all duration-300 bg-gradient-to-br from-card to-red-500/5">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-semibold tracking-wide uppercase text-muted-foreground">Failed Posts</CardTitle>
            <div className="p-2 rounded-lg bg-red-500/10 text-red-500">
              <AlertCircle className="h-5 w-5" />
            </div>
          </CardHeader>
          <CardContent className="pt-2">
            <div className="text-3xl font-extrabold tracking-tight text-red-600 dark:text-red-400">
              {stats?.failed_posts || 0}
            </div>
            <p className="text-xs text-muted-foreground mt-1">Perlu tindakan/perbaikan</p>
          </CardContent>
        </Card>
        
        <Card className="overflow-hidden border-border/50 shadow-md hover:shadow-xl hover:scale-[1.02] transition-all duration-300 bg-gradient-to-br from-card to-indigo-500/5">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-semibold tracking-wide uppercase text-muted-foreground">Next Scheduled</CardTitle>
            <div className="p-2 rounded-lg bg-indigo-500/10 text-indigo-500">
              <Clock className="h-5 w-5" />
            </div>
          </CardHeader>
          <CardContent className="pt-2">
            <div className="text-lg font-bold truncate tracking-tight text-indigo-600 dark:text-indigo-400">
              {next_post_time ? new Date(next_post_time).toLocaleString() : 'Not scheduled'}
            </div>
            <p className="text-xs text-muted-foreground mt-2">Jadwal auto-post berikutnya</p>
          </CardContent>
        </Card>
      </div>

      {/* Main Grid: AI insights, Recent Activity & Chart */}
      <div className="grid gap-6 md:grid-cols-2">
        
        {/* ML Insights */}
        <Card className="border-border/50 shadow-md flex flex-col justify-between">
          <CardHeader>
            <CardTitle className="flex items-center gap-2.5 text-xl">
              <Lightbulb className="h-5 w-5 text-amber-500 animate-pulse" />
              <span>AI Insights & Rekomendasi</span>
            </CardTitle>
            <CardDescription>Analisis performa cerdas berbasis Machine Learning.</CardDescription>
          </CardHeader>
          <CardContent className="flex-1">
            {insights?.status === 'success' && insights?.recommendations?.length > 0 ? (
              <div className="space-y-4">
                {insights.recommendations.map((rec: any, idx: number) => (
                  <div 
                    key={idx} 
                    className={`p-4 rounded-xl border flex gap-3 transition-all hover:scale-[1.01] ${
                      rec.type === 'increase_frequency' 
                        ? 'bg-green-500/5 border-green-500/20 text-green-950 dark:text-green-200' 
                        : 'bg-amber-500/5 border-amber-500/20 text-amber-950 dark:text-amber-200'
                    }`}
                  >
                    <Sparkles className={`h-5 w-5 shrink-0 mt-0.5 ${rec.type === 'increase_frequency' ? 'text-green-500' : 'text-amber-500'}`} />
                    <div>
                      <h4 className="font-bold text-sm flex items-center gap-2">
                        <span>{rec.category}</span>
                        <span className="text-[10px] font-semibold uppercase tracking-wider opacity-70 px-2 py-0.5 rounded bg-background/50 border">
                          {rec.type.replace('_', ' ')}
                        </span>
                      </h4>
                      <p className="text-sm mt-1 text-foreground/80">{rec.action}</p>
                      <p className="text-xs mt-2 opacity-65 italic font-medium">{rec.reason}</p>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-12 text-muted-foreground flex flex-col items-center justify-center">
                <BarChart2 className="h-12 w-12 text-muted-foreground/30 mb-3" />
                <p className="text-sm font-medium">{insights?.message || 'Data belum mencukupi untuk menghasilkan AI insights.'}</p>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Recent Activity */}
        <Card className="border-border/50 shadow-md">
          <CardHeader>
            <CardTitle className="text-xl">Aktivitas Terkini</CardTitle>
            <CardDescription>Catatan publikasi artikel otomatis terakhir.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {logs?.length > 0 ? logs.slice(0, 5).map((log: any, i: number) => (
                <div key={i} className="flex justify-between items-start pb-4 border-b last:border-0 last:pb-0 last:border-none group">
                  <div className="space-y-1 pr-4">
                    <p className="text-sm font-semibold text-foreground/90 group-hover:text-primary transition-colors leading-tight line-clamp-2">
                      {log.title}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      📂 {log.category_name} • {new Date(log.created_at).toLocaleString()}
                    </p>
                  </div>
                  <span className={`px-2.5 py-1 rounded-full text-xs font-semibold shrink-0 shadow-sm border ${
                    log.success 
                      ? 'bg-green-500/10 border-green-500/20 text-green-700 dark:text-green-400' 
                      : 'bg-red-500/10 border-red-500/20 text-red-700 dark:text-red-400'
                  }`}>
                    {log.success ? 'Success' : 'Failed'}
                  </span>
                </div>
              )) : (
                <div className="text-center py-12 text-muted-foreground flex flex-col items-center justify-center">
                  <Clock className="h-12 w-12 text-muted-foreground/30 mb-3" />
                  <p className="text-sm font-medium">Belum ada aktivitas publikasi.</p>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* SVG Analytics Chart */}
      {hasPerfData && (
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
                <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-indigo-500" /> Avg. Engagement Score</span>
              </div>
            </div>
          </CardHeader>
          <CardContent className="pt-2 px-6 pb-6">
            <div className="w-full overflow-x-auto">
              <div className="min-w-[600px] h-[180px] relative">
                <svg className="w-full h-full overflow-visible" viewBox={`0 0 ${chartWidth} ${chartHeight}`}>
                  
                  {/* Grid Lines */}
                  <line x1="40" y1="30" x2={chartWidth - 40} y2="30" stroke="var(--border)" strokeDasharray="3 3" opacity="0.5" />
                  <line x1="40" y1="70" x2={chartWidth - 40} y2="70" stroke="var(--border)" strokeDasharray="3 3" opacity="0.5" />
                  <line x1="40" y1="110" x2={chartWidth - 40} y2="110" stroke="var(--border)" strokeDasharray="3 3" opacity="0.5" />
                  <line x1="40" y1={chartHeight - 30} x2={chartWidth - 40} y2={chartHeight - 30} stroke="var(--border)" opacity="0.8" />
                  
                  {/* Area fill under the path */}
                  <polygon points={areaPoints} fill="url(#chartGrad)" opacity="0.15" />
                  
                  {/* The trend line */}
                  <polyline
                    fill="none"
                    stroke="url(#lineGrad)"
                    strokeWidth="3.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    points={polylinePoints}
                    className="animate-chart"
                  />
                  
                  {/* Data Points */}
                  {chartPoints.map((pt, idx) => (
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
                  {chartPoints.map((pt, idx) => (
                    <text
                      key={idx}
                      x={pt.x}
                      y={chartHeight - 10}
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
      )}

      {/* Category Performance Table */}
      <Card className="border-border/50 shadow-md overflow-hidden">
        <CardHeader>
          <CardTitle>Performa Kategori Detail</CardTitle>
          <CardDescription>Rincian performa postingan dan total keterlibatan per kategori.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {performance?.length > 0 ? (
            <div className="relative w-full overflow-auto">
              <table className="w-full caption-bottom text-sm">
                <thead>
                  <tr className="border-b bg-muted/30 select-none">
                    <th className="h-12 px-6 text-left align-middle font-semibold text-muted-foreground">Kategori</th>
                    <th className="h-12 px-6 text-center align-middle font-semibold text-muted-foreground">Total Post</th>
                    <th className="h-12 px-6 text-center align-middle font-semibold text-muted-foreground">Total View</th>
                    <th className="h-12 px-6 text-center align-middle font-semibold text-muted-foreground">Total Komen</th>
                    <th className="h-12 px-6 text-right align-middle font-semibold text-muted-foreground">Rata-rata Engagement</th>
                  </tr>
                </thead>
                <tbody className="divide-y border-b divide-border/40">
                  {performance.map((cat: any, idx: number) => (
                    <tr key={idx} className="hover:bg-secondary/40 transition-colors">
                      <td className="px-6 py-4 align-middle font-bold text-foreground/95 capitalize">{cat.category}</td>
                      <td className="px-6 py-4 align-middle text-center font-medium text-foreground/80">{cat.total_posts}</td>
                      <td className="px-6 py-4 align-middle text-center font-medium text-foreground/80">{cat.total_views}</td>
                      <td className="px-6 py-4 align-middle text-center font-medium text-foreground/80">{cat.total_comments}</td>
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
      
    </div>
  );
}
