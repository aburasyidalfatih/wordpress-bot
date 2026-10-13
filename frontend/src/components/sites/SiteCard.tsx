import { Edit } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import type { WordPressSite } from '@/lib/types';

interface SiteCardProps {
  site: WordPressSite;
  isSelected: boolean;
  onEdit: () => void;
  onSelect: () => void;
}

const BADGE = 'text-[10px] px-2 py-0.5 rounded-md font-semibold border';

export function SiteCard({ site, isSelected, onEdit, onSelect }: SiteCardProps) {
  return (
    <Card
      className={`group relative overflow-hidden transition-all duration-300 hover:shadow-xl hover:-translate-y-1 border-border/50 ${isSelected ? 'ring-2 ring-primary ring-offset-2 ring-offset-background' : ''}`}
    >
      {/* Background Gradient decoration */}
      <div className="absolute inset-0 bg-gradient-to-br from-primary/5 to-indigo-600/5 opacity-0 group-hover:opacity-100 transition-opacity" />

      <CardHeader className="relative z-10 border-b border-border/40 pb-4 mb-2">
        <div className="flex justify-between items-start">
          <div>
            <CardTitle className="text-xl font-bold">{site.site_name}</CardTitle>
            <CardDescription className="mt-1.5 text-[13px] truncate text-muted-foreground/80" title={site.wordpress_url}>
              {site.wordpress_url}
            </CardDescription>
          </div>
          <div className={`px-2.5 py-1 text-xs font-semibold rounded-full border ${site.is_active ? 'bg-green-500/10 text-green-600 border-green-500/20' : 'bg-muted text-muted-foreground'}`}>
            {site.is_active ? 'Aktif' : 'Dijeda'}
          </div>
        </div>
      </CardHeader>
      <CardContent className="relative z-10 space-y-4">
        <div className="flex flex-wrap gap-2">
          {site.telegram_enabled && <span className={`bg-blue-500/10 text-blue-600 border-blue-500/20 ${BADGE}`}>Telegram</span>}
          {site.facebook_enabled && <span className={`bg-indigo-500/10 text-indigo-600 border-indigo-500/20 ${BADGE}`}>Facebook</span>}
          {site.pinterest_enabled && <span className={`bg-red-500/10 text-red-600 border-red-500/20 ${BADGE}`}>Pinterest</span>}
          {site.twitter_enabled && <span className={`bg-slate-800/10 dark:bg-slate-200/10 text-slate-900 dark:text-slate-100 border-slate-500/20 ${BADGE}`}>X</span>}
          {site.threads_enabled && <span className={`bg-purple-500/10 text-purple-600 border-purple-500/20 ${BADGE}`}>Threads</span>}
        </div>
        <div className="flex items-center justify-between text-sm text-muted-foreground border-t pt-4">
          <span>Kategori</span>
          <span className="font-medium text-foreground bg-secondary px-2 py-0.5 rounded-md">
            {site.selected_categories?.length || 0} / {site.categories?.length || 0}
          </span>
        </div>
      </CardContent>
      <CardFooter className="relative z-10 flex gap-2 px-6 pb-6 pt-4 border-t bg-muted/30">
        <Button
          variant="outline"
          size="sm"
          className="flex-1 min-w-0 bg-background/50 backdrop-blur-sm group-hover:bg-primary group-hover:text-primary-foreground group-hover:border-primary transition-all duration-300"
          onClick={onEdit}
        >
          <Edit className="h-4 w-4 mr-2" /> Konfigurasi
        </Button>
        {!isSelected && (
          <Button variant="ghost" size="sm" className="shrink-0" onClick={onSelect}>
            Pilih
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}
