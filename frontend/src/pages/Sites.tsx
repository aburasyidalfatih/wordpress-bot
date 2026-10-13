import { useState } from 'react';
import { Bot, Plus } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { useSiteContext } from '@/hooks/useSiteContext';
import { useSearchConsoleReturnToast } from '@/hooks/useSearchConsole';
import { NEW_SITE_DEFAULTS } from '@/hooks/useSiteForm';
import { SiteCard } from '@/components/sites/SiteCard';
import { SiteEditor } from '@/components/sites/SiteEditor';
import type { SiteDraft } from '@/lib/types';

export default function Sites() {
  const { sites, setSelectedSiteId, selectedSiteId } = useSiteContext();
  const [editingSite, setEditingSite] = useState<SiteDraft | null>(null);
  useSearchConsoleReturnToast();

  if (editingSite) {
    return <SiteEditor initialSite={editingSite} onClose={() => setEditingSite(null)} />;
  }

  const handleCreateNew = () => setEditingSite({ ...NEW_SITE_DEFAULTS });

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-primary to-indigo-600 bg-clip-text text-transparent flex items-center gap-3">
            <Bot className="h-8 w-8 text-primary" /> Website
          </h1>
          <p className="text-muted-foreground mt-1">Kelola website WordPress dan integrasinya tanpa batas.</p>
        </div>
        <Button onClick={handleCreateNew} className="rounded-xl shadow-lg shadow-primary/20 bg-gradient-to-r from-primary to-indigo-600 hover:opacity-90">
          <Plus className="h-5 w-5 mr-2" /> Website Baru
        </Button>
      </div>

      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {sites.map(site => (
          <SiteCard
            key={site.id}
            site={site}
            isSelected={selectedSiteId === site.id}
            onEdit={() => setEditingSite(site)}
            onSelect={() => {
              setSelectedSiteId(site.id);
              toast.success(`Beralih ke website ${site.site_name}`);
            }}
          />
        ))}

        {sites.length === 0 && (
          <div className="col-span-full py-20 text-center border-2 border-dashed rounded-2xl bg-muted/20">
            <Bot className="h-16 w-16 mx-auto text-muted-foreground opacity-50 mb-4" />
            <h3 className="text-xl font-bold text-foreground">Belum Ada Website</h3>
            <p className="text-muted-foreground mt-2 mb-6 max-w-sm mx-auto">Hubungkan website WordPress pertama Anda untuk mulai membuat dan menjadwalkan artikel.</p>
            <Button onClick={handleCreateNew} className="rounded-xl shadow-lg bg-gradient-to-r from-primary to-indigo-600 hover:opacity-90">
              <Plus className="h-5 w-5 mr-2" /> Buat Website Pertama
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
