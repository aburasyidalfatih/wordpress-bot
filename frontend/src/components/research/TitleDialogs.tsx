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
import { clampTitleCount, MAX_TITLES_PER_REQUEST } from './researchHelpers';

interface GenerateTitlesDialogProps {
  category: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Raw input text; clamped to 1..20 when generating. */
  count: string;
  onCountChange: (count: string) => void;
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
          <Label htmlFor="titleCount" className="text-sm font-medium">Jumlah Judul (1-{MAX_TITLES_PER_REQUEST})</Label>
          <Input
            id="titleCount"
            type="number"
            inputMode="numeric"
            min={1}
            max={MAX_TITLES_PER_REQUEST}
            step={1}
            value={count}
            onChange={(e) => onCountChange(e.target.value)}
            onBlur={() => { if (count.trim() !== '') onCountChange(String(clampTitleCount(count, 1))); }}
            className="text-lg"
          />
        </div>
        <DialogFooter className="sm:justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>Batal</Button>
          <Button onClick={onGenerate} className="bg-indigo-600 hover:bg-indigo-700 text-white gap-2">
            <Sparkles className="h-4 w-4" /> Buat {clampTitleCount(count, 1)} Judul
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export interface BulkTitleRow {
  /** Unique key of the category (see categoryKey). */
  key: string;
  name: string;
  /** Why titles cannot be generated for this category; null when they can. */
  blockReason: string | null;
}

interface BulkGenerateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  rows: BulkTitleRow[];
  /** Raw input text per row key; clamped to 0..20 when generating. */
  counts: Record<string, string>;
  onCountsChange: (counts: Record<string, string>) => void;
  onGenerate: () => void;
}

export function BulkGenerateDialog({ open, onOpenChange, rows, counts, onCountsChange, onGenerate }: BulkGenerateDialogProps) {
  const total = rows
    .filter(row => !row.blockReason)
    .reduce((sum, row) => sum + clampTitleCount(counts[row.key] ?? '', 0), 0);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg max-h-[90vh] flex flex-col">
        <DialogHeader className="shrink-0">
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-indigo-600" /> Buat Judul Massal
          </DialogTitle>
          <DialogDescription>
            Tentukan jumlah judul (0-{MAX_TITLES_PER_REQUEST}) untuk masing-masing kategori. Isi 0 untuk melewati kategori.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-4 overflow-y-auto min-h-[300px]">
          {rows.map((row, index) => {
            const inputId = `bulk-title-count-${index}`;
            const reasonId = `${inputId}-reason`;
            const blocked = !!row.blockReason;
            return (
              <div key={row.key} className={`flex items-center justify-between gap-4 p-3 rounded-lg border bg-card ${blocked ? 'opacity-70' : ''}`}>
                <div className="flex-1 min-w-0">
                  <Label htmlFor={inputId} className="text-base font-semibold capitalize">{row.name}</Label>
                  {blocked && <p id={reasonId} className="mt-1 text-xs text-muted-foreground">{row.blockReason}</p>}
                </div>
                <div className="flex items-center gap-2 w-32">
                  <Input
                    id={inputId}
                    type="number"
                    inputMode="numeric"
                    min={0}
                    max={MAX_TITLES_PER_REQUEST}
                    step={1}
                    disabled={blocked}
                    aria-describedby={blocked ? reasonId : undefined}
                    value={blocked ? '0' : counts[row.key] ?? ''}
                    onChange={(e) => onCountsChange({ ...counts, [row.key]: e.target.value })}
                    onBlur={() => {
                      const raw = counts[row.key] ?? '';
                      if (!blocked && raw.trim() !== '') onCountsChange({ ...counts, [row.key]: String(clampTitleCount(raw, 0)) });
                    }}
                    className="text-right"
                  />
                </div>
              </div>
            );
          })}
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
