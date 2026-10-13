import { RefreshCw, Eye, AlertCircle, Trash2 } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import type { HistoryItem } from '@/lib/types';

interface HistoryItemCardProps {
  item: HistoryItem;
  regenerating: boolean;
  onRegenerate: (kind: 'image' | 'article') => void;
  onDelete: () => void;
}

export function HistoryItemCard({ item, regenerating, onRegenerate, onDelete }: HistoryItemCardProps) {
  const spinner = <RefreshCw className={`h-4 w-4 mr-2 ${regenerating ? 'animate-spin' : ''}`} />;
  return (
    <Card className="bg-card">
      <CardContent className="p-6 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-blue-600 text-white shadow-sm border border-transparent">
              {item.category}
            </span>
            <span className={`text-xs font-semibold px-2.5 py-0.5 rounded-full shadow-sm border border-transparent ${item.success ? 'bg-green-600 text-white' : 'bg-red-600 text-white'}`}>
              {item.success ? 'TERBIT' : 'GAGAL'}
            </span>
            {item.success && item.image_failed && (
              <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 border border-amber-200 dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-800/50 flex items-center gap-1">
                <AlertCircle className="w-3 h-3" /> Gambar Gagal
              </span>
            )}
          </div>
          <h3 className="font-semibold text-lg">{item.title}</h3>
          <p className="text-xs text-muted-foreground mt-2">Diposting: {new Date(item.timestamp).toLocaleString()}</p>
          {(!item.success || item.image_failed) && (
            <p className="text-xs text-red-500 mt-1 bg-red-50 p-2 rounded border border-red-100">{item.result}</p>
          )}
        </div>

        {item.success && item.post_url && (
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              className="text-amber-600 border-amber-200 hover:bg-amber-50"
              disabled={regenerating}
              onClick={() => onRegenerate('image')}
            >
              {spinner}
              Buat Ulang Gambar
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="text-blue-600 border-blue-200 hover:bg-blue-50"
              disabled={regenerating}
              onClick={() => onRegenerate('article')}
            >
              {spinner}
              Buat Ulang Artikel
            </Button>
            <Button variant="outline" size="icon" onClick={() => window.open(item.post_url, '_blank')} className="text-purple-600 hover:text-purple-700 hover:bg-purple-50 z-20" title="Lihat Artikel">
              <Eye className="h-4 w-4" />
            </Button>
            <Button variant="outline" size="icon" onClick={onDelete} className="text-red-600 hover:text-red-700 hover:bg-red-50 border-red-200 z-20" title="Hapus Artikel & Riwayat">
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
