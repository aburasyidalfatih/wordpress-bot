import { Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import type { SiteCategory } from '@/lib/types';

interface GenerateTitlesDialogProps {
  category: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  count: number;
  onCountChange: (count: number) => void;
  onGenerate: () => void;
}

export function GenerateTitlesDialog({ category, open, onOpenChange, count, onCountChange, onGenerate }: GenerateTitlesDialogProps) {
  return (
    <Dialog open={open && !!category} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-indigo-600" /> Buat Judul AI
          </DialogTitle>
          <DialogDescription>
            Berapa judul artikel menarik yang ingin Anda buat secara otomatis untuk kategori <b>{category}</b>?
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 py-4">
          <Label htmlFor="titleCount" className="text-sm font-medium">Jumlah Judul (1-20)</Label>
          <Input
            id="titleCount"
            type="number"
            min="1"
            max="20"
            value={count}
            onChange={(e) => onCountChange(parseInt(e.target.value) || 1)}
            className="text-lg"
          />
        </div>
        <DialogFooter className="sm:justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>Batal</Button>
          <Button onClick={onGenerate} className="bg-indigo-600 hover:bg-indigo-700 text-white gap-2">
            <Sparkles className="h-4 w-4" /> Buat Sekarang
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface BulkGenerateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  categories: SiteCategory[];
  counts: Record<string, number>;
  onCountsChange: (counts: Record<string, number>) => void;
  onGenerate: () => void;
}

export function BulkGenerateDialog({ open, onOpenChange, categories, counts, onCountsChange, onGenerate }: BulkGenerateDialogProps) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg max-h-[90vh] flex flex-col">
        <DialogHeader className="shrink-0">
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-indigo-600" /> Buat Judul Massal
          </DialogTitle>
          <DialogDescription>
            Tentukan jumlah judul yang ingin Anda buat untuk masing-masing kategori.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-4 overflow-y-auto min-h-[300px]">
          {categories.map((cat) => (
            <div key={cat.name} className="flex items-center justify-between gap-4 p-3 rounded-lg border bg-card">
              <div className="flex-1">
                <Label className="text-base font-semibold capitalize">{cat.name}</Label>
              </div>
              <div className="flex items-center gap-2 w-32">
                <Input
                  type="number"
                  min="0"
                  max="50"
                  value={counts[cat.name] || 0}
                  onChange={(e) => onCountsChange({ ...counts, [cat.name]: parseInt(e.target.value) || 0 })}
                  className="text-right"
                />
              </div>
            </div>
          ))}
        </div>
        <DialogFooter className="sm:justify-between shrink-0 pt-4 border-t">
          <div className="text-sm font-medium text-muted-foreground self-center">
            Total: <span className="text-indigo-600 font-bold">{total} Judul</span>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>Batal</Button>
            <Button onClick={onGenerate} disabled={total === 0} className="bg-indigo-600 hover:bg-indigo-700 text-white gap-2">
              <Sparkles className="h-4 w-4" /> Buat Massal
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
