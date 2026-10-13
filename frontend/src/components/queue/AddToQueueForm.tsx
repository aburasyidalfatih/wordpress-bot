import { useState } from 'react';
import { Plus } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { SiteCategory } from '@/lib/types';

interface AddToQueueFormProps {
  categories: SiteCategory[];
  // Title and category are owned by the page so they survive the loading
  // spinner that replaces this form while the queue reloads.
  title: string;
  onTitleChange: (title: string) => void;
  category: string;
  onCategoryChange: (category: string) => void;
  /** Resolves to true when the title was added. */
  onAdd: (title: string, category: string) => Promise<boolean>;
}

export function AddToQueueForm({ categories, title, onTitleChange, category, onCategoryChange, onAdd }: AddToQueueFormProps) {
  const [adding, setAdding] = useState(false);

  // Keep the chosen category valid for the current site: when switching sites
  // (or when the site's categories change) and the previous choice isn't among
  // them, fall back to the first available category.
  const selectedCategory = categories.some(c => c.name === category)
    ? category
    : (categories[0]?.name ?? '');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title || !selectedCategory) return;
    setAdding(true);
    if (await onAdd(title, selectedCategory)) onTitleChange('');
    setAdding(false);
  };

  return (
    <Card className="border-border/50 shadow-md">
      <CardHeader>
        <CardTitle>Tambah Judul Manual</CardTitle>
        <CardDescription>Masukkan ide artikel secara manual ke antrean penerbitan.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="flex gap-4 items-center">
          <label htmlFor="category-select" className="sr-only">Kategori</label>
          <select
            id="category-select"
            value={selectedCategory}
            onChange={e => onCategoryChange(e.target.value)}
            className="flex h-10 w-[300px] items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {categories.length === 0 ? (
              <option value="" disabled>Kategori tidak ditemukan</option>
            ) : (
              categories.map((cat) => (
                <option key={cat.id} value={cat.name}>{cat.name}</option>
              ))
            )}
          </select>
          <Input
            placeholder="Judul artikel..."
            value={title}
            onChange={e => onTitleChange(e.target.value)}
            className="flex-1 h-10 text-base"
          />
          <Button type="submit" disabled={adding || !title || !selectedCategory} className="h-10 px-5 text-sm">
            <Plus className="h-4 w-4 mr-2" />
            Tambah ke Antrean
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
