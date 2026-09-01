import { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '../lib/api';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RefreshCw, TrendingUp, Video, MessageCircle, FileText, BarChart, Search, Sparkles, Trash2, ShieldCheck, AlertTriangle, ExternalLink, Clock, SearchCheck, MousePointerClick } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useSiteContext } from '@/contexts/SiteContext';
import EmptyState from '@/components/EmptyState';
import { ErrorState } from '@/components/ErrorState';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { toast } from 'sonner';

export interface ResearchDataResponse {
  categories: CategoryType[];
  research_data: Record<string, ResearchStats>;
  search_console?: {
    connected: boolean;
    property_url?: string | null;
    last_synced_at?: string | null;
    opportunities: SearchOpportunity[];
  };
}

interface SearchOpportunity {
  type: 'quick_win' | 'low_ctr' | 'declining';
  query: string;
  page: string;
  clicks: number;
  impressions: number;
  ctr: number;
  position: number;
  click_change: number;
  position_change?: number | null;
  opportunity_score: number;
  rationale: string;
}

export interface CategoryType {
  id: number;
  name: string;
  description?: string;
}

export interface ResearchStats {
  created_at: string;
  trend_score: number;
  keywords: string[];
  quality_score: number;
  confidence_level: 'high' | 'medium' | 'low' | 'insufficient' | 'unknown';
  is_fallback: boolean;
  is_stale: boolean;
  age_hours: number | null;
  long_tail_keywords: string[];
  semantic_context: string;
  news_insights: { title: string; source?: string; url?: string; published_at?: string }[];
  source_metadata: Record<string, { status?: string; count?: number; checked_at?: string; reason?: string }>;
  social_insights: ({ text: string; url?: string; provider?: string } | string)[];
  competitor_outlines: {
    title: string;
    url: string;
    headers: string[];
  }[];
  youtube_insights: {
    title: string;
    snippets: string;
    url?: string;
    transcript_available?: boolean;
  }[];
}

const confidenceLabel: Record<string, string> = {
  high: 'Tinggi', medium: 'Sedang', low: 'Rendah',
  insufficient: 'Tidak mencukupi', unknown: 'Data lama',
};

const confidenceClass: Record<string, string> = {
  high: 'bg-emerald-100 text-emerald-700 border-emerald-200',
  medium: 'bg-blue-100 text-blue-700 border-blue-200',
  low: 'bg-amber-100 text-amber-700 border-amber-200',
  insufficient: 'bg-red-100 text-red-700 border-red-200',
  unknown: 'bg-muted text-muted-foreground border-border',
};

export default function Research() {
  const { selectedSiteId } = useSiteContext();
  const [data, setData] = useState<ResearchDataResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
    const [researching, setResearching] = useState(false);
  const [researchingCategory, setResearchingCategory] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  const [jobId, setJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [generatingFor, setGeneratingFor] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [modalCategory, setModalCategory] = useState<string | null>(null);
  const [titleCount, setTitleCount] = useState<number>(1);
  const [bulkModalOpen, setBulkModalOpen] = useState(false);
  const [bulkCounts, setBulkCounts] = useState<Record<string, number>>({});
  const navigate = useNavigate();

  const loadData = useCallback((signal?: AbortSignal) => {
    if (!selectedSiteId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setLoadError(null);
    apiFetch(`/api/research_data?site_id=${selectedSiteId}&_t=${Date.now()}`, { signal })
      .then(async res => {
        const payload = await res.json().catch(() => ({}));
        if (!res.ok || !payload.success) {
          throw new Error(payload.error || `Gagal memuat data riset (${res.status})`);
        }
        return payload;
      })
      .then(d => {
        setData(d);
      })
      .catch(err => {
        if (err.name !== 'AbortError') {
          setData(null);
          setLoadError(err instanceof Error ? err.message : 'Gagal memuat data riset.');
          if (import.meta.env.DEV) console.error('Failed to load research data:', err);
        }
      })
      .finally(() => {
        if (!signal?.aborted) setLoading(false);
      });
  }, [selectedSiteId]);

  useEffect(() => {
    const controller = new AbortController();
    loadData(controller.signal);
    return () => controller.abort();
  }, [loadData]);

  useEffect(() => {
    if (!jobId) return;

    const controller = new AbortController();
    const interval = setInterval(async () => {
      try {
        const res = await apiFetch(`/api/job-status/${jobId}`, { signal: controller.signal });
        const result = await res.json();
        
        if (result.success) {
          setProgress(result.progress);
          setMessage(`${result.progress}% - ${result.message}`);
          
          if (result.status === 'finished') {
            clearInterval(interval);
            setResearching(false);
            setResearchingCategory(null);
            setJobId(null);
            setMessage('Analysis complete! Reloading data...');
            setTimeout(() => loadData(), 1000);
          } else if (result.status === 'failed') {
            clearInterval(interval);
            setResearching(false);
            setResearchingCategory(null);
            setJobId(null);
            setMessage('Research job failed.');
          }
        }
      } catch (e) {
        if (e instanceof DOMException && e.name === 'AbortError') return;
        if (import.meta.env.DEV) console.error("Polling error", e);
      }
    }, 2000);

    return () => {
      clearInterval(interval);
      controller.abort();
    };
  }, [jobId, loadData]);

  const handleClearResearch = async () => {
    if (!selectedSiteId) return;
    
    
    
    try {
      const res = await apiFetch('/api/clear-research', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ site_id: selectedSiteId })
      });
      const result = await res.json();
      if (result.success) {
        setMessage(result.message);
        loadData();
      } else {
        setMessage('Gagal menghapus riset: ' + result.error);
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : String(err);
      setMessage(`Network error: ${errorMsg}`);
    }
  };

  const handleManualResearch = async (categoryName?: string) => {
    if (!selectedSiteId) return;
    setResearching(true);
    setResearchingCategory(categoryName || 'all');
    setProgress(0);
    setMessage(categoryName ? `Initializing deep research for category "${categoryName}"...` : 'Initializing deep enterprise research...');
    try {
      const url = categoryName 
        ? `/manual-research?site_id=${selectedSiteId}&category=${encodeURIComponent(categoryName)}`
        : `/manual-research?site_id=${selectedSiteId}`;
      const res = await apiFetch(url, { method: 'POST' });
      const result = await res.json();
      if (result.success && result.job_id) {
        setJobId(result.job_id);
        window.dispatchEvent(new Event('refresh-profile'));
      } else {
        setMessage(result.error || 'Research failed to start.');
        setResearching(false);
        setResearchingCategory(null);
      }
    } catch (err) {
      setMessage('Network error during research.');
      setResearching(false);
      setResearchingCategory(null);
    }
  };

  const handleGenerateTitles = async () => {
    if (!modalCategory || !selectedSiteId) return;
    const category = modalCategory;
    setGeneratingFor(category);
    setIsModalOpen(false);
    try {
      const res = await apiFetch(`/api/generate-titles/${encodeURIComponent(category)}?site_id=${selectedSiteId}`, { 
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ count: titleCount })
      });
      const result = await res.json();
      if (result.success) {
        setMessage(`Success: ${result.message}`);
        setTimeout(() => navigate('/queue'), 1500);
      } else {
        setMessage(result.error || 'Failed to generate titles.');
      }
    } catch (err) {
      setMessage('Network error while generating titles.');
    } finally {
      setGeneratingFor(null);
    }
  };

  const handleOpenBulkModal = () => {
    if (!data?.categories) return;
    const initialCounts: Record<string, number> = {};
    data.categories.forEach((cat: CategoryType) => {
      initialCounts[cat.name] = 1; // Default 1 per category
    });
    setBulkCounts(initialCounts);
    setBulkModalOpen(true);
  };

  const handleExecuteBulkGenerate = async () => {
    if (!selectedSiteId) return;
    setResearching(true);
    setMessage('Memulai proses generate judul massal...');
    setBulkModalOpen(false);
    
    let totalGenerated = 0;
    const categoriesToProcess = Object.entries(bulkCounts).filter(([_, count]) => count > 0);
    
    for (let i = 0; i < categoriesToProcess.length; i++) {
      const [category, count] = categoriesToProcess[i];
      setMessage(`Generating ${count} judul untuk ${category} (${i+1}/${categoriesToProcess.length})...`);
      setProgress(Math.round(((i) / categoriesToProcess.length) * 100));
      
      try {
        const res = await apiFetch(`/api/generate-titles/${encodeURIComponent(category)}?site_id=${selectedSiteId}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ count })
        });
        const result = await res.json();
        if (result.success) {
          totalGenerated += count;
        } else {
          toast.error(`Gagal generate judul untuk ${category}: ${result.error}`);
        }
      } catch (err) {
        if (import.meta.env.DEV) console.error('Failed for', category, err);
        toast.error(`Network error generate judul untuk ${category}`);
      }
    }
    
    setProgress(100);
    setMessage(`Selesai! ${totalGenerated} judul berhasil ditambahkan ke antrean.`);
    setResearching(false);
    setTimeout(() => navigate('/queue'), 2000);
  };

  if (loading) return <div className="p-8 flex items-center justify-center min-h-[400px]">
    <div className="flex flex-col items-center gap-4 text-muted-foreground">
      <RefreshCw className="h-8 w-8 animate-spin text-primary" />
      Loading research intelligence...
    </div>
  </div>;

  if (!selectedSiteId) return <EmptyState title="Intelligence Hub" description="Pilih salah satu website Anda dari menu dropdown di kanan atas untuk memuat analisis kompetitor, tren sosial, dan topik terhangat." />;

  if (loadError) return <div className="p-8"><ErrorState message={loadError} onRetry={() => loadData()} /></div>;

  const researchData = data?.research_data || {};
  const selectedCategories = data?.categories || [];

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-primary to-indigo-600 dark:from-primary dark:to-indigo-400 bg-clip-text text-transparent flex items-center gap-2">
            <Search className="h-8 w-8 text-primary" /> Intelligence Hub
          </h1>
          <p className="text-muted-foreground mt-1">Deep competitor analysis, social listening, and trend tracking.</p>
        </div>
        {selectedCategories.length > 0 && (
          <div className="flex gap-2">
            <AlertDialog>
              <AlertDialogTrigger render={
                <Button disabled={researching || Object.keys(researchData).length === 0} variant="outline" className="gap-2 font-semibold shadow-sm hover:shadow-md transition-all text-red-600 border-red-200 hover:bg-red-50 hover:text-red-700 dark:hover:bg-red-900/20">
                  <Trash2 className="h-4 w-4" />
                  Bersihkan Riset
                </Button>
              }>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Apakah Anda yakin?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Tindakan ini akan menghapus SEMUA hasil riset untuk website ini secara permanen. Anda harus melakukan riset dari awal lagi setelahnya.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Batal</AlertDialogCancel>
                  <AlertDialogAction onClick={handleClearResearch} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">Ya, Hapus Riset</AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
            <Button onClick={handleOpenBulkModal} disabled={researching} variant="outline" className="gap-2 font-semibold shadow-sm hover:shadow-md transition-all text-indigo-600 border-indigo-200 hover:bg-indigo-50">
              <Sparkles className="h-4 w-4" />
              Buat Judul Massal
            </Button>
            <Button onClick={() => handleManualResearch()} disabled={researching} className="gap-2 shadow-lg hover:shadow-primary/25 transition-all bg-primary hover:bg-primary/95 text-primary-foreground font-semibold">
              <RefreshCw className={`h-4 w-4 ${researching && researchingCategory === 'all' ? 'animate-spin' : ''}`} />
              {researching && researchingCategory === 'all' ? 'Menganalisis...' : `Riset Semua Kategori (${selectedCategories.length} Kredit)`}
            </Button>
          </div>
        )}
      </div>

      {message && (
        <div aria-live="polite" className={`p-4 rounded-xl text-sm font-medium border shadow-sm ${message.includes('fail') || message.includes('error') ? 'bg-red-50 text-red-800 border-red-200 dark:bg-red-900/20' : 'bg-blue-50 text-blue-800 border-blue-200 dark:bg-blue-900/20'}`}>
          <div className="flex justify-between mb-2">
            <span>{message}</span>
            {researching && <span>{progress}%</span>}
          </div>
          {researching && (
            <div className="w-full bg-blue-200/50 rounded-full h-2 overflow-hidden">
              <div 
                className="bg-blue-600 h-2 rounded-full transition-all duration-500 ease-out" 
                style={{ width: `${progress}%` }} 
              />
            </div>
          )}
        </div>
      )}

      {data?.search_console?.connected && (
        <Card className="overflow-hidden border-emerald-200/70 shadow-md">
          <CardHeader className="border-b bg-gradient-to-r from-emerald-50 to-background">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <CardTitle className="flex items-center gap-2 text-xl"><SearchCheck className="h-5 w-5 text-emerald-600" /> Search Console Opportunities</CardTitle>
                <CardDescription className="mt-1">Quick wins dari performa pencarian aktual website, bukan estimasi keyword eksternal.</CardDescription>
              </div>
              <div className="text-right text-xs text-muted-foreground">
                <p>{data.search_console.property_url}</p>
                {data.search_console.last_synced_at && <p>Sync: {new Date(data.search_console.last_synced_at).toLocaleString('id-ID')}</p>}
              </div>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {data.search_console.opportunities?.length ? (
              <div className="divide-y">
                {data.search_console.opportunities.slice(0, 8).map((item, index) => (
                  <div key={`${item.query}-${item.page}-${index}`} className="grid gap-3 p-4 hover:bg-muted/20 md:grid-cols-[1fr_auto]">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${item.type === 'quick_win' ? 'bg-emerald-100 text-emerald-700' : item.type === 'low_ctr' ? 'bg-blue-100 text-blue-700' : 'bg-red-100 text-red-700'}`}>
                          {item.type.replace('_', ' ')}
                        </span>
                        <span className="rounded-full border px-2 py-0.5 text-xs font-semibold">Opportunity {item.opportunity_score}/100</span>
                      </div>
                      <p className="mt-2 font-semibold text-foreground">{item.query}</p>
                      <a href={item.page} target="_blank" rel="noreferrer" className="mt-1 block truncate text-xs text-muted-foreground hover:underline">{item.page}</a>
                      <p className="mt-2 text-xs text-muted-foreground">{item.rationale}</p>
                    </div>
                    <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs md:min-w-[230px]">
                      <span className="text-muted-foreground">Impressions</span><strong>{item.impressions.toLocaleString('id-ID')}</strong>
                      <span className="text-muted-foreground">Clicks</span><strong>{item.clicks.toLocaleString('id-ID')}</strong>
                      <span className="text-muted-foreground">CTR</span><strong>{item.ctr}%</strong>
                      <span className="text-muted-foreground">Position</span><strong>{item.position}</strong>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex items-center gap-3 p-6 text-sm text-muted-foreground">
                <MousePointerClick className="h-5 w-5" /> Belum ada opportunity. Jalankan sinkronisasi dari konfigurasi Website.
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {!data?.search_console?.connected && selectedCategories.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-dashed bg-muted/10 p-4">
          <div><p className="font-semibold">Aktifkan first-party SEO intelligence</p><p className="text-sm text-muted-foreground">Hubungkan Google Search Console untuk menemukan keyword posisi 4–20, CTR rendah, dan penurunan klik.</p></div>
          <Button variant="outline" onClick={() => navigate('/sites')}><SearchCheck className="mr-2 h-4 w-4" /> Hubungkan Search Console</Button>
        </div>
      )}

      {selectedCategories.length === 0 ? (
        <Card className="border-dashed border-2">
          <CardContent className="py-16 text-center flex flex-col items-center">
            <Search className="h-12 w-12 text-muted-foreground/50 mb-4" />
            <p className="text-xl font-medium text-foreground mb-2">Belum ada kategori target.</p>
            <p className="text-sm text-muted-foreground max-w-md">Silakan edit website ini di menu Websites, hubungkan kategori WordPress Anda, lalu pilih kategori target yang ingin dipantau.</p>
            <Button onClick={() => navigate('/sites')} className="mt-4 gap-2 bg-indigo-600 hover:bg-indigo-700 text-white font-semibold">
              Konfigurasi Website
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-6 xl:grid-cols-2">
          {selectedCategories.map((catObj: CategoryType) => {
            const cat = catObj.name;
            const stats = researchData[cat];
            
            if (!stats) {
              return (
                <Card key={cat} className="overflow-hidden border-dashed border-2 border-border bg-muted/15 p-6 flex flex-col justify-between min-h-[220px] shadow-sm hover:border-primary/50 transition-all duration-300">
                  <div className="space-y-2">
                    <h3 className="text-xl font-bold capitalize text-muted-foreground/90">{cat}</h3>
                    <p className="text-sm text-muted-foreground leading-relaxed">
                      {catObj.description || 'Belum ada data riset intelijen untuk kategori ini. Mulai riset kategori ini secara terpisah untuk menemukan tren kata kunci kompetitor, tren sosial, dan video YouTube terpopuler.'}
                    </p>
                  </div>
                  <div className="pt-4 flex justify-start">
                    <Button 
                      onClick={() => handleManualResearch(cat)} 
                      disabled={researching} 
                      className="gap-2 bg-primary hover:bg-primary/90 text-primary-foreground shadow-md transition-all font-semibold"
                    >
                      <RefreshCw className={`h-4 w-4 ${researching && researchingCategory === cat ? 'animate-spin' : ''}`} />
                      Mulai Riset Kategori (1 Kredit)
                    </Button>
                  </div>
                </Card>
              );
            }
            
            const trendScore = stats.trend_score || 0;
            
            return (
              <Card key={cat} className="overflow-hidden border-border/50 shadow-md hover:shadow-xl transition-all duration-300 group">
                <CardHeader className="bg-gradient-to-r from-muted/50 to-muted/10 border-b pb-6">
                  <div className="flex justify-between items-start">
                    <div>
                      <CardTitle className="text-2xl capitalize mb-2 group-hover:text-primary transition-colors">{cat}</CardTitle>
                      <CardDescription className="flex flex-wrap items-center gap-2">
                        <TrendingUp className="h-4 w-4 text-green-500" />
                        Trend Score: <span className="font-bold text-foreground">{trendScore > 0 ? `${trendScore}/100` : 'Tidak tersedia'}</span>
                        <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold ${confidenceClass[stats.confidence_level] || confidenceClass.unknown}`}>
                          <ShieldCheck className="h-3 w-3" />
                          Confidence {confidenceLabel[stats.confidence_level] || 'Data lama'} · {stats.quality_score || 0}/100
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
                          onClick={() => handleManualResearch(cat)}
                          disabled={researching}
                          className="gap-1 border-primary/30 text-primary hover:bg-primary/5 hover:text-primary bg-background/50 font-semibold"
                        >
                          <RefreshCw className={`h-3.5 w-3.5 ${researching && researchingCategory === cat ? 'animate-spin' : ''}`} />
                          Riset Ulang (1 Kredit)
                        </Button>
                        <Button 
                          size="sm" 
                          onClick={() => {
                            setModalCategory(cat);
                            setIsModalOpen(true);
                          }} 
                          disabled={generatingFor === cat}
                          className="bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm gap-1"
                        >
                          <Sparkles className={`h-3.5 w-3.5 ${generatingFor === cat ? 'animate-pulse' : ''}`} />
                          {generatingFor === cat ? 'Thinking...' : 'Generate AI Titles'}
                        </Button>
                      </div>
                    </div>
                  </div>
                  {(stats.is_stale || stats.is_fallback || stats.confidence_level === 'unknown') && (
                    <div className="mt-4 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                      <span>
                        {stats.is_stale
                          ? 'Data ini berusia lebih dari 7 hari. Riset ulang sebelum membuat keputusan konten.'
                          : stats.confidence_level === 'unknown'
                            ? 'Data ini dibuat sebelum sistem quality scoring tersedia. Riset ulang untuk hasil terverifikasi.'
                            : 'Sebagian data memakai fallback dan tidak dianggap sebagai bukti sumber nyata.'}
                      </span>
                    </div>
                  )}
                  <div className="w-full bg-secondary rounded-full h-2 mt-4 overflow-hidden">
                    <div className="bg-primary h-2 rounded-full transition-all" style={{ width: `${Math.min(100, Math.max(0, stats.quality_score || 0))}%` }} />
                  </div>
                </CardHeader>
                
                <CardContent className="p-0">
                  <div className="grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x border-b">
                    
                    {/* Keywords Section */}
                    <div className="p-6 space-y-4 bg-primary/5">
                      <div className="flex items-center gap-2 font-semibold text-primary">
                        <BarChart className="h-4 w-4" />
                        <span>Top Keywords</span>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {stats.keywords && stats.keywords.length > 0 ? (
                          stats.keywords.map((kw: string, i: number) => (
                            <span key={i} className="text-xs px-2.5 py-1 bg-background border shadow-sm rounded-full text-foreground/80 hover:text-foreground transition-colors">
                              {kw}
                            </span>
                          ))
                        ) : (
                          <span className="text-xs text-muted-foreground italic">No keywords found</span>
                        )}
                      </div>
                    </div>

                    {/* Social Insights */}
                    <div className="p-6 space-y-4">
                      <div className="flex items-center gap-2 font-semibold text-orange-600">
                        <MessageCircle className="h-4 w-4" />
                        <span>Social Listening</span>
                      </div>
                      <ul className="space-y-3">
                        {stats.social_insights && stats.social_insights.length > 0 ? (
                          stats.social_insights.map((item, i: number) => {
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
                          <li className="text-sm text-muted-foreground italic">No recent social discussions</li>
                        )}
                      </ul>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x">
                    
                    {/* Competitors Section */}
                    <div className="p-6 space-y-4">
                      <div className="flex items-center gap-2 font-semibold text-blue-600">
                        <FileText className="h-4 w-4" />
                        <span>Top Competitors</span>
                      </div>
                      <div className="space-y-4">
                        {stats.competitor_outlines && stats.competitor_outlines.length > 0 ? (
                          stats.competitor_outlines.map((comp, i: number) => (
                            <div key={i} className="space-y-1">
                              <a href={comp.url} target="_blank" rel="noreferrer" className="text-sm font-medium hover:underline text-foreground line-clamp-1">
                                {comp.title}
                              </a>
                              <div className="flex flex-wrap gap-1">
                                {comp.headers && comp.headers.slice(0,3).map((h:string, j:number) => (
                                  <span key={j} className="text-[10px] px-1.5 py-0.5 bg-muted text-muted-foreground rounded truncate max-w-[120px]">
                                    {h}
                                  </span>
                                ))}
                              </div>
                            </div>
                          ))
                        ) : (
                          <div className="text-sm text-muted-foreground italic">No competitor data</div>
                        )}
                      </div>
                    </div>

                    {/* YouTube Insights */}
                    <div className="p-6 space-y-4 bg-red-50/30">
                      <div className="flex items-center gap-2 font-semibold text-red-600">
                        <Video className="h-4 w-4" />
                        <span>Video Insights</span>
                      </div>
                      <div className="space-y-3">
                        {stats.youtube_insights && stats.youtube_insights.length > 0 ? (
                          stats.youtube_insights.map((yt, i: number) => (
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
                          <div className="text-sm text-muted-foreground italic">No video transcripts found</div>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="border-t p-6 space-y-5 bg-muted/10">
                    <div className="flex items-center gap-2 font-semibold">
                      <ShieldCheck className="h-4 w-4 text-emerald-600" />
                      Transparansi Sumber
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {Object.entries(stats.source_metadata || {})
                        .filter(([, meta]) => meta && typeof meta === 'object' && 'status' in meta)
                        .map(([provider, meta]) => (
                          <span key={provider} className={`rounded-full border px-2.5 py-1 text-xs ${
                            meta.status === 'real' ? 'border-emerald-200 bg-emerald-50 text-emerald-700' :
                            meta.status === 'partial' ? 'border-blue-200 bg-blue-50 text-blue-700' :
                            meta.status === 'fallback' ? 'border-amber-200 bg-amber-50 text-amber-700' :
                            'border-border bg-background text-muted-foreground'
                          }`}>
                            {provider.replaceAll('_', ' ')}: {meta.status || 'unknown'}
                            {typeof meta.count === 'number' ? ` (${meta.count})` : ''}
                          </span>
                        ))}
                    </div>

                    {stats.long_tail_keywords?.length > 0 && (
                      <div>
                        <p className="mb-2 text-sm font-semibold">Long-tail opportunities</p>
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

                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      {/* Generation Modal */}
      <Dialog open={isModalOpen && !!modalCategory} onOpenChange={setIsModalOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-indigo-600" /> Generate AI Titles
            </DialogTitle>
            <DialogDescription>
              Berapa judul artikel menarik yang ingin Anda buat secara otomatis untuk kategori <b>{modalCategory}</b>?
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-4">
            <Label htmlFor="titleCount" className="text-sm font-medium">Jumlah Judul (1-20)</Label>
            <Input 
              id="titleCount" 
              type="number" 
              min="1" 
              max="20" 
              value={titleCount} 
              onChange={(e) => setTitleCount(parseInt(e.target.value) || 1)}
              className="text-lg"
            />
          </div>
          <DialogFooter className="sm:justify-end gap-2">
            <Button variant="outline" onClick={() => setIsModalOpen(false)}>Batal</Button>
            <Button onClick={handleGenerateTitles} className="bg-indigo-600 hover:bg-indigo-700 text-white gap-2">
              <Sparkles className="h-4 w-4" /> Generate Sekarang
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Bulk Generation Modal */}
      <Dialog open={bulkModalOpen} onOpenChange={setBulkModalOpen}>
        <DialogContent className="sm:max-w-lg max-h-[90vh] flex flex-col">
          <DialogHeader className="shrink-0">
            <DialogTitle className="flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-indigo-600" /> Buat Judul Massal
            </DialogTitle>
            <DialogDescription>
              Tentukan jumlah judul yang ingin Anda generate untuk masing-masing kategori.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4 overflow-y-auto min-h-[300px]">
            {selectedCategories.map((catObj: CategoryType) => (
              <div key={catObj.name} className="flex items-center justify-between gap-4 p-3 rounded-lg border bg-card">
                <div className="flex-1">
                  <Label className="text-base font-semibold capitalize">{catObj.name}</Label>
                </div>
                <div className="flex items-center gap-2 w-32">
                  <Input 
                    type="number" 
                    min="0" 
                    max="50" 
                    value={bulkCounts[catObj.name] || 0} 
                    onChange={(e) => setBulkCounts(prev => ({ ...prev, [catObj.name]: parseInt(e.target.value) || 0 }))}
                    className="text-right"
                  />
                </div>
              </div>
            ))}
          </div>
          <DialogFooter className="sm:justify-between shrink-0 pt-4 border-t">
            <div className="text-sm font-medium text-muted-foreground self-center">
              Total: <span className="text-indigo-600 font-bold">{Object.values(bulkCounts).reduce((a, b) => a + b, 0)} Judul</span>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setBulkModalOpen(false)}>Batal</Button>
              <Button onClick={handleExecuteBulkGenerate} disabled={Object.values(bulkCounts).reduce((a, b) => a + b, 0) === 0} className="bg-indigo-600 hover:bg-indigo-700 text-white gap-2">
                <Sparkles className="h-4 w-4" /> Generate Massal
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
