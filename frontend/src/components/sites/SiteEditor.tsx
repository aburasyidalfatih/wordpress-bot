import { useState } from 'react';
import { Trash2, ChevronRight } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { useSiteForm } from '@/hooks/useSiteForm';
import { useSearchConsole } from '@/hooks/useSearchConsole';
import type { SiteDraft } from '@/lib/types';
import { SITE_TABS, type SiteTabId } from './siteForm';
import { WordPressTab } from './WordPressTab';
import { AutomationTab } from './AutomationTab';
import { SearchConsoleTab } from './SearchConsoleTab';
import { TelegramTab, FacebookTab, PinterestTab, TwitterTab, ThreadsTab } from './SocialTabs';

interface SiteEditorProps {
  initialSite: SiteDraft;
  onClose: () => void;
}

export function SiteEditor({ initialSite, onClose }: SiteEditorProps) {
  const { site, updateSite, handleChange, saving, handleSave, deleteSite, fetchCategories } = useSiteForm(initialSite, onClose);
  const gsc = useSearchConsole(site.id, updateSite);
  const [activeTab, setActiveTab] = useState<SiteTabId>('wordpress');
  const [confirmDelete, setConfirmDelete] = useState(false);
  const tabProps = { site, updateSite, onChange: handleChange };
  const activeLabel = SITE_TABS.find(tab => tab.id === activeTab)?.label;

  return (
    <div className="space-y-6 animate-in fade-in zoom-in-95 duration-300">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-primary to-indigo-600 bg-clip-text text-transparent">
            {site.id ? 'Edit Website' : 'Website Baru'}
          </h1>
          <p className="text-muted-foreground mt-1">Atur integrasi WordPress dan aturan otomatisasi website Anda.</p>
        </div>
        <Button variant="outline" onClick={onClose}>Batal</Button>
      </div>

      <div className="flex flex-col md:flex-row gap-6">
        {/* Vertical Tabs */}
        <div className="w-full md:w-64 space-y-1" role="tablist" aria-orientation="vertical">
          {SITE_TABS.map((tab) => (
            <button
              key={tab.id}
              role="tab"
              aria-selected={activeTab === tab.id}
              aria-controls={`panel-${tab.id}`}
              id={`tab-${tab.id}`}
              onClick={() => setActiveTab(tab.id)}
              className={`w-full flex items-center justify-between px-4 py-3 rounded-xl text-sm font-medium transition-all ${
                activeTab === tab.id
                  ? 'bg-primary text-primary-foreground shadow-md scale-[1.02]'
                  : 'text-muted-foreground hover:bg-secondary hover:text-foreground'
              }`}
            >
              <span>{tab.label}</span>
              {activeTab === tab.id && <ChevronRight className="h-4 w-4" />}
            </button>
          ))}
        </div>

        {/* Form Content */}
        <div className="flex-1">
          <Card className="border-border/50 shadow-xl bg-card/80 backdrop-blur-sm">
            <form onSubmit={handleSave}>
              <CardHeader className="pb-6 border-b mb-6">
                <CardTitle className="text-xl">Konfigurasi {activeLabel}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-6 min-h-[400px] pb-8">
                {activeTab === 'wordpress' && <WordPressTab {...tabProps} onFetchCategories={fetchCategories} />}
                {activeTab === 'automation' && <AutomationTab {...tabProps} />}
                {activeTab === 'telegram' && <TelegramTab {...tabProps} />}
                {activeTab === 'facebook' && <FacebookTab {...tabProps} />}
                {activeTab === 'pinterest' && <PinterestTab {...tabProps} />}
                {activeTab === 'twitter' && <TwitterTab {...tabProps} />}
                {activeTab === 'threads' && <ThreadsTab {...tabProps} />}
                {activeTab === 'search-console' && <SearchConsoleTab site={site} onChange={handleChange} gsc={gsc} />}
              </CardContent>
              <CardFooter className="flex justify-between border-t p-6 bg-muted/10">
                <div className="flex gap-2">
                  {site.id && (
                    <Button type="button" variant="destructive" onClick={() => setConfirmDelete(true)}>
                      <Trash2 className="h-4 w-4 mr-2" /> Hapus Website
                    </Button>
                  )}
                </div>
                <div className="flex gap-3">
                  <Button type="button" variant="ghost" onClick={onClose}>Batal</Button>
                  <Button type="submit" disabled={saving} className="bg-gradient-to-r from-primary to-indigo-600 shadow-md hover:opacity-90">
                    {saving ? 'Menyimpan...' : 'Simpan Konfigurasi'}
                  </Button>
                </div>
              </CardFooter>
            </form>

            <ConfirmDialog
              open={confirmDelete}
              onCancel={() => setConfirmDelete(false)}
              onConfirm={async () => {
                if (site.id) await deleteSite(site.id);
                setConfirmDelete(false);
              }}
              description="Tindakan ini tidak dapat dibatalkan. Website ini beserta seluruh log terkait akan dihapus permanen dari database bot."
              confirmLabel="Hapus Website"
              destructive
            />
          </Card>
        </div>
      </div>
    </div>
  );
}
