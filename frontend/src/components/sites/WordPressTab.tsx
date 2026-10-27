import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { SiteCategory } from '@/lib/types';
import { TabPanel } from './TabPanel';
import { SAVED_SECRET_PLACEHOLDER, type SiteTabProps } from './siteForm';

const Required = () => <span className="text-red-500">*</span>;

export function WordPressTab({ site, updateSite, onChange, onFetchCategories }: SiteTabProps & { onFetchCategories: () => void }) {
  return (
    <TabPanel id="wordpress">
      <div className="space-y-2">
        <Label htmlFor="site_name">Nama Website <Required /></Label>
        <Input id="site_name" name="site_name" required value={site.site_name || ''} onChange={onChange} placeholder="Blog Keren Saya" />
      </div>
      <div className="space-y-2">
        <Label htmlFor="wordpress_url">URL WordPress <Required /></Label>
        <Input id="wordpress_url" name="wordpress_url" required value={site.wordpress_url || ''} onChange={onChange} placeholder="https://blogsaya.com" />
      </div>
      <div className="space-y-2">
        <Label htmlFor="wordpress_username">Username WordPress <Required /></Label>
        <Input id="wordpress_username" name="wordpress_username" required value={site.wordpress_username || ''} onChange={onChange} />
      </div>
      <div className="space-y-2">
        <Label htmlFor="wordpress_password">Application Password {!site.id && <Required />}</Label>
        <Input
          id="wordpress_password"
          name="wordpress_password"
          required={!site.id}
          type="password"
          value={site.wordpress_password || ''}
          onChange={onChange}
          placeholder={site.id ? (site.has_wordpress_password ? SAVED_SECRET_PLACEHOLDER : 'Belum tersimpan.') : ''}
        />
        <p className="text-xs text-muted-foreground">Gunakan Application Password WordPress, bukan password login utama Anda.</p>
      </div>

      {site.id && (
        <CategoryPicker
          categories={site.categories || []}
          selected={site.selected_categories || []}
          onChangeSelection={(selected_categories) => updateSite({ selected_categories })}
          onFetchCategories={onFetchCategories}
        />
      )}
      {site.id && (site.categories || []).length > 0 && (
        <CategoryHints
          categories={site.categories || []}
          onChange={(categories) => updateSite({ categories })}
        />
      )}
    </TabPanel>
  );
}

const MAX_CATEGORY_HINT_CHARS = 2000;

interface CategoryHintsProps {
  categories: SiteCategory[];
  onChange: (categories: SiteCategory[]) => void;
}

/** Private per-category AI instructions; saved with the site, never published to WordPress. */
function CategoryHints({ categories, onChange }: CategoryHintsProps) {
  const setHint = (id: number, ai_hint: string) =>
    onChange(categories.map(cat => (cat.id === id ? { ...cat, ai_hint } : cat)));
  const filled = categories.filter(cat => (cat.ai_hint || '').trim()).length;

  return (
    <details className="pt-4 border-t group">
      <summary className="cursor-pointer font-medium">
        Petunjuk AI per kategori (tidak tampil di website)
        {filled > 0 && <span className="ml-2 text-xs text-muted-foreground">{filled} kategori terisi</span>}
      </summary>
      <p className="text-xs text-muted-foreground mt-2">
        Tulis instruksi khusus untuk AI di sini, misalnya pembaca sasaran atau frasa yang perlu dipakai. Petunjuk ini
        hanya disimpan di AutoWP dan dipakai saat menulis artikel. Jangan taruh instruksi seperti ini di deskripsi
        kategori WordPress, karena deskripsi itu tampil publik di website.
      </p>
      <div className="space-y-3 mt-3 max-h-80 overflow-y-auto pr-1">
        {categories.map(cat => (
          <div key={cat.id} className="space-y-1">
            <Label htmlFor={`cat_hint_${cat.id}`} className="text-sm">{cat.name}</Label>
            <textarea
              id={`cat_hint_${cat.id}`}
              value={cat.ai_hint || ''}
              maxLength={MAX_CATEGORY_HINT_CHARS}
              rows={2}
              onChange={(e) => setHint(cat.id, e.target.value)}
              placeholder="Contoh: Sasar kepala sekolah SMA swasta; hindari istilah teknis tanpa penjelasan."
              className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>
        ))}
      </div>
    </details>
  );
}

interface CategoryPickerProps {
  categories: SiteCategory[];
  selected: SiteCategory[];
  onChangeSelection: (selected: SiteCategory[]) => void;
  onFetchCategories: () => void;
}

function CategoryPicker({ categories, selected, onChangeSelection, onFetchCategories }: CategoryPickerProps) {
  const selectAll = () => onChangeSelection([...categories]);
  const clearAll = () => onChangeSelection([]);
  const allSelected = categories.length > 0 && selected.length === categories.length;

  return (
    <div className="pt-4 border-t space-y-4">
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-3">
          <h3 className="font-medium">Kategori</h3>
          {categories.length > 0 && (
            <div className="flex items-center gap-2 border-l pl-3 ml-1">
              <Button type="button" variant="link" size="xs" className="p-0 text-xs font-bold text-primary hover:no-underline" onClick={selectAll}>
                Centang Semua
              </Button>
              <span className="text-muted-foreground/30 text-[10px]">|</span>
              <Button type="button" variant="link" size="xs" className="p-0 text-xs font-bold text-muted-foreground hover:no-underline" onClick={clearAll}>
                Hapus Semua
              </Button>
            </div>
          )}
        </div>
        <Button type="button" variant="outline" size="sm" onClick={onFetchCategories}>
          <RefreshCw className="h-4 w-4 mr-2" /> Ambil Kategori
        </Button>
      </div>

      {categories.length > 0 ? (
        <div className="space-y-2 max-h-48 overflow-y-auto p-3 border rounded-xl bg-muted/30">
          <div className="flex items-center space-x-3 p-1 border-b pb-2 mb-2">
            <input
              type="checkbox"
              id="select_all_categories_checkbox"
              checked={allSelected}
              onChange={(e) => (e.target.checked ? selectAll() : clearAll())}
              className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary cursor-pointer"
            />
            <Label htmlFor="select_all_categories_checkbox" className="font-bold text-primary cursor-pointer text-xs uppercase tracking-wider">
              Centang Semua
            </Label>
          </div>
          {categories.map((cat) => (
            <div key={cat.id} className="flex items-center space-x-3 p-1">
              <input
                type="checkbox"
                id={`cat_${cat.id}`}
                name="selected_categories"
                value={cat.id}
                checked={selected.some(c => c.id === cat.id)}
                onChange={(e) => onChangeSelection(
                  e.target.checked ? [...selected, cat] : selected.filter(c => c.id !== cat.id)
                )}
                className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
              />
              <Label htmlFor={`cat_${cat.id}`} className="font-medium cursor-pointer">
                {cat.name} <span className="text-xs text-muted-foreground ml-1">({cat.count ?? 0} artikel)</span>
              </Label>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">Belum ada kategori. Simpan website terlebih dahulu, lalu klik Ambil Kategori.</p>
      )}
    </div>
  );
}
