import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { RefreshCw, Search, Sparkles } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { useSiteContext } from '@/hooks/useSiteContext';
import { useResearch } from '@/hooks/useResearch';
import EmptyState from '@/components/EmptyState';
import { ErrorState } from '@/components/ErrorState';
import { ResearchStatusBanner } from '@/components/research/ResearchStatusBanner';
import { ConnectSearchConsolePrompt, SearchConsoleOpportunities } from '@/components/research/SearchConsoleOpportunities';
import { CategoryResearchCard, EmptyCategoryCard } from '@/components/research/CategoryResearchCard';
import { BulkGenerateDialog, GenerateTitlesDialog } from '@/components/research/TitleDialogs';
import { ClearResearchButton } from '@/components/research/ClearResearchButton';

export default function Research() {
  const { selectedSiteId } = useSiteContext();
  const research = useResearch(selectedSiteId);
  const navigate = useNavigate();

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [modalCategory, setModalCategory] = useState<string | null>(null);
  const [titleCount, setTitleCount] = useState<number>(1);
  const [bulkModalOpen, setBulkModalOpen] = useState(false);
  const [bulkCounts, setBulkCounts] = useState<Record<string, number>>({});

  if (research.loading) return (
    <div className="p-8 flex items-center justify-center min-h-[400px]">
      <div className="flex flex-col items-center gap-4 text-muted-foreground">
        <RefreshCw className="h-8 w-8 animate-spin text-primary" />
        Memuat data riset...
      </div>
    </div>
  );

  if (!selectedSiteId) return <EmptyState title="Intelligence Hub" description="Pilih salah satu website Anda dari menu dropdown di kanan atas untuk memuat analisis kompetitor, tren sosial, dan topik terhangat." />;

  if (research.loadError) return <div className="p-8"><ErrorState message={research.loadError} onRetry={research.reload} /></div>;

  const { data, researching, researchingCategory } = research;
  const researchData = data?.research_data || {};
  const selectedCategories = data?.categories || [];

  const openBulkModal = () => {
    // Default to one title per category.
    setBulkCounts(Object.fromEntries(selectedCategories.map(cat => [cat.name, 1])));
    setBulkModalOpen(true);
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div className="flex flex-col xl:flex-row justify-between items-start xl:items-center gap-4">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-primary to-indigo-600 dark:from-primary dark:to-indigo-400 bg-clip-text text-transparent flex items-center gap-2">
            <Search className="h-8 w-8 text-primary" /> Intelligence Hub
          </h1>
          <p className="text-muted-foreground mt-1">Analisis kompetitor mendalam, social listening, dan pemantauan tren.</p>
        </div>
        {selectedCategories.length > 0 && (
          <div className="flex flex-wrap gap-2">
            <ClearResearchButton disabled={researching || Object.keys(researchData).length === 0} onConfirm={research.clearResearch} />
            <Button onClick={openBulkModal} disabled={researching} variant="outline" className="gap-2 font-semibold shadow-sm hover:shadow-md transition-all text-indigo-600 border-indigo-200 hover:bg-indigo-50">
              <Sparkles className="h-4 w-4" />
              Buat Judul Massal
            </Button>
            <Button onClick={() => research.startResearch()} disabled={researching} className="gap-2 shadow-lg hover:shadow-primary/25 transition-all bg-primary hover:bg-primary/95 text-primary-foreground font-semibold">
              <RefreshCw className={`h-4 w-4 ${researching && researchingCategory === 'all' ? 'animate-spin' : ''}`} />
              {researching && researchingCategory === 'all' ? 'Menganalisis...' : `Riset Semua Kategori (${selectedCategories.length} Kredit)`}
            </Button>
          </div>
        )}
      </div>

      {research.status && (
        <ResearchStatusBanner status={research.status} researching={researching} progress={research.progress} />
      )}

      {data?.search_console?.connected && <SearchConsoleOpportunities summary={data.search_console} />}

      {!data?.search_console?.connected && selectedCategories.length > 0 && <ConnectSearchConsolePrompt />}

      {selectedCategories.length === 0 ? (
        <Card className="border-dashed border-2">
          <CardContent className="py-16 text-center flex flex-col items-center">
            <Search className="h-12 w-12 text-muted-foreground/50 mb-4" />
            <p className="text-xl font-medium text-foreground mb-2">Belum ada kategori target.</p>
            <p className="text-sm text-muted-foreground max-w-md">Silakan edit website ini di menu Website, hubungkan kategori WordPress Anda, lalu pilih kategori target yang ingin dipantau.</p>
            <Button onClick={() => navigate('/sites')} className="mt-4 gap-2 bg-indigo-600 hover:bg-indigo-700 text-white font-semibold">
              Konfigurasi Website
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-6 xl:grid-cols-2">
          {selectedCategories.map((category) => {
            const name = category.name;
            const stats = researchData[name];
            const actions = {
              researching,
              isResearchingThis: researching && researchingCategory === name,
              onResearch: () => research.startResearch(name),
            };
            if (!stats) return <EmptyCategoryCard key={name} category={category} {...actions} />;
            return (
              <CategoryResearchCard
                key={name}
                name={name}
                stats={stats}
                {...actions}
                isGenerating={research.generatingFor === name}
                onGenerateTitles={() => {
                  setModalCategory(name);
                  setIsModalOpen(true);
                }}
              />
            );
          })}
        </div>
      )}

      <GenerateTitlesDialog
        category={modalCategory}
        open={isModalOpen}
        onOpenChange={setIsModalOpen}
        count={titleCount}
        onCountChange={setTitleCount}
        onGenerate={() => {
          if (!modalCategory) return;
          setIsModalOpen(false);
          research.generateTitles(modalCategory, titleCount);
        }}
      />

      <BulkGenerateDialog
        open={bulkModalOpen}
        onOpenChange={setBulkModalOpen}
        categories={selectedCategories}
        counts={bulkCounts}
        onCountsChange={setBulkCounts}
        onGenerate={() => {
          setBulkModalOpen(false);
          research.generateTitlesInBulk(bulkCounts);
        }}
      />
    </div>
  );
}
