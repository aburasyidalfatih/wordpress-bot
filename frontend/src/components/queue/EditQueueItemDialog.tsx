import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { QueueItem } from '@/lib/types';

interface EditQueueItemDialogProps {
  item: QueueItem;
  onClose: () => void;
  /** Resolves to true when the edit was saved. */
  onSave: (title: string, keywords: string, sendKeywords: boolean) => Promise<boolean>;
}

/** Modal for editing a queued title; mount it with key={item.id}. */
export function EditQueueItemDialog({ item, onClose, onSave }: EditQueueItemDialogProps) {
  const [title, setTitle] = useState(item.title);
  const [keywords, setKeywords] = useState(item.target_keywords || '');

  const handleSave = async () => {
    // Only send keywords when the current value is known or the user typed some.
    if (await onSave(title, keywords, item.target_keywords !== undefined || !!keywords)) onClose();
  };

  return (
    <div className="fixed inset-0 z-50 bg-background/80 backdrop-blur-sm flex items-center justify-center p-4">
      <Card className="w-full max-w-lg shadow-lg">
        <CardHeader>
          <CardTitle>Edit Item Antrean</CardTitle>
          <CardDescription>Ubah judul dan kata kunci target sebelum diposting.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm font-medium">Judul</label>
            <Input value={title} onChange={e => setTitle(e.target.value)} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Kata Kunci</label>
            <Input value={keywords} onChange={e => setKeywords(e.target.value)} placeholder="Kata kunci dipisahkan koma" />
          </div>
          <div className="flex justify-end gap-2 pt-4">
            <Button variant="outline" onClick={onClose}>Batal</Button>
            <Button onClick={handleSave}>Simpan Perubahan</Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
