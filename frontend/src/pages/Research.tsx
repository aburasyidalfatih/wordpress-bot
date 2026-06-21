import { useState, useEffect } from 'react';
import { apiFetch } from '../lib/api';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RefreshCw, TrendingUp, Video, MessageCircle, FileText, BarChart, Search, Sparkles } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useSiteContext } from '@/contexts/SiteContext';
import EmptyState from '@/components/EmptyState';

export default function Research() {
  const { selectedSiteId } = useSiteContext();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [researching, setResearching] = useState(false);
  const [researchingCategory, setResearchingCategory] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  const [jobId, setJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [generatingFor, setGeneratingFor] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [modalCategory, setModalCategory] = useState<string | null>(null);
  const [titleCount, setTitleCount] = useState<number>(5);
  const navigate = useNavigate();

  const loadData = () => {
    if (!selectedSiteId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    apiFetch(`/api/research_data?site_id=${selectedSiteId}`)
      .then(res => res.json())
      .then(d => {
        setData(d);
        setLoading(false);
      });
  };

  useEffect(() => {
    loadData();
  }, [selectedSiteId]);

  useEffect(() => {
    if (!jobId) return;

    const interval = setInterval(async () => {
      try {
        const res = await apiFetch(`/api/job-status/${jobId}`);
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
            setTimeout(loadData, 1000);
          } else if (result.status === 'failed') {
            clearInterval(interval);
            setResearching(false);
            setResearchingCategory(null);
            setJobId(null);
            setMessage('Research job failed.');
          }
        }
      } catch (e) {
        console.error("Polling error", e);
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [jobId]);

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

  if (loading) return <div className="p-8 flex items-center justify-center min-h-[400px]">
    <div className="flex flex-col items-center gap-4 text-muted-foreground">
      <RefreshCw className="h-8 w-8 animate-spin text-primary" />
      Loading research intelligence...
    </div>
  </div>;

  if (!selectedSiteId) return <EmptyState title="Intelligence Hub" description="Pilih salah satu website Anda dari menu dropdown di kanan atas untuk memuat analisis kompetitor, tren sosial, dan topik terhangat." />;

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
          <Button onClick={() => handleManualResearch()} disabled={researching} className="gap-2 shadow-lg hover:shadow-primary/25 transition-all bg-primary hover:bg-primary/95 text-primary-foreground font-semibold">
            <RefreshCw className={`h-4 w-4 ${researching && researchingCategory === 'all' ? 'animate-spin' : ''}`} />
            {researching && researchingCategory === 'all' ? 'Menganalisis...' : `Riset Semua Kategori (${selectedCategories.length} Kredit)`}
          </Button>
        )}
      </div>

      {message && (
        <div className={`p-4 rounded-xl text-sm font-medium border shadow-sm ${message.includes('fail') || message.includes('error') ? 'bg-red-50 text-red-800 border-red-200' : 'bg-blue-50 text-blue-800 border-blue-200'}`}>
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
          {selectedCategories.map((catObj: any) => {
            const cat = catObj.name;
            const stats = researchData[cat];
            
            if (!stats) {
              return (
                <Card key={cat} className="overflow-hidden border-dashed border-2 border-border bg-muted/15 p-6 flex flex-col justify-between min-h-[220px] shadow-sm hover:border-primary/50 transition-all duration-300">
                  <div className="space-y-2">
                    <h3 className="text-xl font-bold capitalize text-muted-foreground/90">{cat}</h3>
                    <p className="text-sm text-muted-foreground leading-relaxed">Belum ada data riset intelijen untuk kategori ini. Mulai riset kategori ini secara terpisah untuk menemukan tren kata kunci kompetitor, tren sosial, dan video YouTube terpopuler.</p>
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
                      <CardDescription className="flex items-center gap-2">
                        <TrendingUp className="h-4 w-4 text-green-500" />
                        Trend Score: <span className="font-bold text-foreground">{trendScore}/100</span>
                      </CardDescription>
                    </div>
                    <div className="flex flex-col items-end gap-2">
                      <span className="text-xs text-muted-foreground bg-background/80 backdrop-blur-sm px-2.5 py-1 rounded-full border shadow-sm">
                        {stats.created_at}
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
                  <div className="w-full bg-secondary rounded-full h-2 mt-4 overflow-hidden">
                    <div className="bg-primary h-2 rounded-full transition-all" style={{ width: `${Math.min(100, Math.max(0, trendScore))}%` }} />
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
                          stats.social_insights.map((q: string, i: number) => (
                            <li key={i} className="text-sm text-muted-foreground leading-snug flex gap-2">
                              <span className="text-orange-500 font-bold">•</span> {q}
                            </li>
                          ))
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
                          stats.competitor_outlines.map((comp: any, i: number) => (
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
                          stats.youtube_insights.map((yt: any, i: number) => (
                            <div key={i} className="text-sm">
                              <p className="font-medium line-clamp-1 mb-1">{yt.title}</p>
                              <p className="text-xs text-muted-foreground line-clamp-3 bg-white/50 p-2 rounded border border-red-100">
                                "{yt.snippets}"
                              </p>
                            </div>
                          ))
                        ) : (
                          <div className="text-sm text-muted-foreground italic">No video transcripts found</div>
                        )}
                      </div>
                    </div>
                  </div>

                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      {/* Generation Modal */}
      {isModalOpen && modalCategory && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <Card className="w-full max-w-md animate-in fade-in zoom-in-95 shadow-2xl border-0">
            <CardHeader className="border-b bg-muted/20">
              <CardTitle className="flex items-center gap-2">
                <Sparkles className="h-5 w-5 text-indigo-600" /> Generate AI Titles
              </CardTitle>
              <CardDescription>Berapa judul artikel menarik yang ingin Anda buat secara otomatis untuk kategori <b>{modalCategory}</b>?</CardDescription>
            </CardHeader>
            <CardContent className="p-6">
              <div className="space-y-3">
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
            </CardContent>
            <div className="flex items-center p-6 pt-0 justify-end gap-3 bg-muted/20 border-t mt-4 rounded-b-xl">
              <Button variant="outline" onClick={() => setIsModalOpen(false)}>Batal</Button>
              <Button onClick={handleGenerateTitles} className="bg-indigo-600 hover:bg-indigo-700 text-white gap-2">
                <Sparkles className="h-4 w-4" /> Generate Sekarang
              </Button>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
