import { Link } from 'react-router-dom';
import { Plus } from 'lucide-react';
import { useSiteContext } from '@/hooks/useSiteContext';

/** Dropdown that switches the selected website; "mobile" is the drawer variant. */
export function SiteSelector({ mobile = false }: { mobile?: boolean }) {
  const { sites, selectedSiteId, setSelectedSiteId, loading } = useSiteContext();

  if (loading) {
    return <div className={mobile ? 'h-10 w-full animate-pulse rounded-lg bg-muted' : 'h-9 w-48 lg:w-64 animate-pulse rounded-md bg-muted'}></div>;
  }

  const select = (
    <select
      value={selectedSiteId || ''}
      onChange={(e) => setSelectedSiteId(e.target.value ? parseInt(e.target.value, 10) : null)}
      className={mobile
        ? 'h-10 w-full rounded-lg border border-input bg-card/80 px-3 py-2 text-sm shadow-sm transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 hover:bg-accent'
        : 'h-9 w-48 lg:w-64 rounded-lg border border-input bg-card/80 backdrop-blur-sm px-3 py-1 text-sm shadow-sm transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 hover:bg-accent cursor-pointer font-medium text-foreground/90'}
    >
      {sites.length > 0 && !selectedSiteId && <option disabled value="">Pilih website...</option>}
      {sites.map(site => (
        <option key={site.id} value={site.id} className="bg-background text-foreground">
          {mobile ? site.site_name : `🌐 ${site.site_name}`}
        </option>
      ))}
      {sites.length === 0 && <option disabled value="">Belum ada website</option>}
    </select>
  );

  if (mobile) return select;

  return (
    <div className="flex items-center gap-2">
      {select}
      {sites.length === 0 && (
        <Link to="/sites" className="flex items-center gap-1 text-xs text-primary hover:text-primary/80 font-bold transition-colors ml-1 bg-primary/5 border border-primary/20 px-2.5 py-1 rounded-lg">
          <Plus className="h-3 w-3" />
          Tambah Website
        </Link>
      )}
    </div>
  );
}
