import { useState } from 'react';
import { RefreshCw, LayoutList, Shuffle, Trash2 } from 'lucide-react';
import { DndContext, closestCenter, KeyboardSensor, PointerSensor, useSensor, useSensors } from '@dnd-kit/core';
import { SortableContext, sortableKeyboardCoordinates, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { Button } from '@/components/ui/button';
import { useSiteContext } from '@/hooks/useSiteContext';
import { useQueueData } from '@/hooks/useQueueData';
import { useQueueActions } from '@/hooks/useQueueActions';
import EmptyState from '@/components/EmptyState';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { SortableQueueItem } from '@/components/queue/SortableQueueItem';
import { HistoryItemCard } from '@/components/queue/HistoryItemCard';
import { AddToQueueForm } from '@/components/queue/AddToQueueForm';
import { EditQueueItemDialog } from '@/components/queue/EditQueueItemDialog';
import type { QueueItem } from '@/lib/types';

type ConfirmAction =
  | { type: 'delete'; id: number }
  | { type: 'post'; id: number }
  | { type: 'delete_history'; id: number }
  | { type: 'clear' };

const CONFIRM_TEXT: Record<ConfirmAction['type'], string> = {
  delete: 'Tindakan ini tidak dapat dibatalkan. Judul ini akan dihapus permanen dari antrean.',
  clear: 'Peringatan: Semua artikel di antrean website ini akan dihapus secara permanen.',
  delete_history: 'Log ini akan dihapus dan artikelnya akan dicoba dipindahkan ke tempat sampah WordPress.',
  post: 'Artikel ini akan langsung diproses dan diposting sekarang.',
};

const TAB_CLASS = 'px-4 py-2 border-b-2 font-medium text-sm transition-colors';
const tabClass = (active: boolean) =>
  `${TAB_CLASS} ${active ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}`;

export default function Queue() {
  const { selectedSiteId, sites } = useSiteContext();
  const queue = useQueueData(selectedSiteId);
  const actions = useQueueActions(selectedSiteId, queue);
  const [activeTab, setActiveTab] = useState<'queue' | 'history'>('queue');
  const [newTitle, setNewTitle] = useState('');
  const [newCategory, setNewCategory] = useState('');
  const [editingItem, setEditingItem] = useState<QueueItem | null>(null);
  const [shuffling, setShuffling] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [confirmAction, setConfirmAction] = useState<ConfirmAction | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  if (!selectedSiteId) return <EmptyState title="Antrean Artikel" description="Pilih salah satu website Anda dari menu dropdown di kanan atas untuk mengelola antrean penerbitan artikel AI." />;
  if (queue.loading) return <div className="p-8 flex items-center justify-center">
    <RefreshCw className="h-8 w-8 animate-spin text-primary" />
  </div>;

  const { items, historyItems, regeneratingIds } = queue;
  const availableCategories = sites.find(s => s.id === selectedSiteId)?.categories || [];
  const pendingItems = items.filter(i => i.status !== 'posted' && i.status !== 'failed');

  const handleShuffle = async () => {
    setShuffling(true);
    await actions.shuffle();
    setShuffling(false);
  };

  const runConfirmedAction = async () => {
    const action = confirmAction;
    if (!action) return;
    if (action.type === 'clear') {
      setClearing(true);
      await actions.clearQueue();
      setClearing(false);
    } else if (action.type === 'delete') {
      await actions.deleteItem(action.id);
    } else if (action.type === 'post') {
      await actions.postNow(action.id);
    } else {
      await actions.deleteHistory(action.id);
    }
    setConfirmAction(null);
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-primary to-indigo-600 dark:from-primary dark:to-indigo-400 bg-clip-text text-transparent flex items-center gap-2">
          <LayoutList className="h-8 w-8 text-primary" /> Antrean Konten
        </h1>
        <p className="text-muted-foreground mt-1">Kelola judul hasil AI dan ide manual yang menunggu diterbitkan.</p>
      </div>

      <AddToQueueForm
        categories={availableCategories}
        title={newTitle}
        onTitleChange={setNewTitle}
        category={newCategory}
        onCategoryChange={setNewCategory}
        onAdd={actions.addTitle}
      />

      <div className="flex justify-between items-center border-b border-muted">
        <div className="flex">
          <button className={tabClass(activeTab === 'queue')} onClick={() => setActiveTab('queue')}>
            Menunggu / Draf ({pendingItems.length})
          </button>
          <button className={tabClass(activeTab === 'history')} onClick={() => setActiveTab('history')}>
            Riwayat ({historyItems.length})
          </button>
        </div>
        {activeTab === 'queue' && (
          <div className="flex gap-2 mb-2">
            <Button variant="outline" size="sm" onClick={() => setConfirmAction({ type: 'clear' })} disabled={clearing || pendingItems.length === 0} className="text-red-600 hover:text-red-700 hover:bg-red-50 border-red-200 dark:hover:bg-red-950/50">
              <Trash2 className={`h-4 w-4 mr-2 ${clearing ? 'animate-spin' : ''}`} />
              Hapus Semua Antrean
            </Button>
            <Button variant="outline" size="sm" onClick={handleShuffle} disabled={shuffling || items.length <= 1}>
              <Shuffle className={`h-4 w-4 mr-2 ${shuffling ? 'animate-spin' : ''}`} />
              Acak Urutan
            </Button>
          </div>
        )}
      </div>

      {activeTab === 'queue' ? (
        <div className="grid gap-4">
          {pendingItems.length === 0 ? (
            <div className="text-center p-8 text-muted-foreground bg-muted/50 rounded-xl">
              Antrean kosong. Buka halaman Riset untuk membuat judul baru!
            </div>
          ) : (
            <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={actions.reorder}>
              <SortableContext items={pendingItems.map(i => i.id)} strategy={verticalListSortingStrategy}>
                {pendingItems.map(item => (
                  <SortableQueueItem
                    key={item.id}
                    item={item}
                    onDelete={(id) => setConfirmAction({ type: 'delete', id })}
                    onEdit={setEditingItem}
                    onPostNow={(id) => setConfirmAction({ type: 'post', id })}
                  />
                ))}
              </SortableContext>
            </DndContext>
          )}
        </div>
      ) : (
        <div className="grid gap-4">
          {historyItems.length === 0 ? (
            <div className="text-center p-8 text-muted-foreground bg-muted/50 rounded-xl">
              Belum ada riwayat.
            </div>
          ) : (
            historyItems.map(item => (
              <HistoryItemCard
                key={item.id}
                item={item}
                regenerating={!!regeneratingIds[item.id]}
                onRegenerate={(kind) => actions.regenerate(item.id, kind)}
                onDelete={() => setConfirmAction({ type: 'delete_history', id: item.id })}
              />
            ))
          )}
        </div>
      )}

      {editingItem && (
        <EditQueueItemDialog
          key={editingItem.id}
          item={editingItem}
          onClose={() => setEditingItem(null)}
          onSave={(title, keywords, sendKeywords) => actions.saveEdit(editingItem.id, title, keywords, sendKeywords)}
        />
      )}

      <ConfirmDialog
        open={!!confirmAction}
        onCancel={() => setConfirmAction(null)}
        onConfirm={runConfirmedAction}
        description={confirmAction ? CONFIRM_TEXT[confirmAction.type] : ''}
        destructive={confirmAction?.type !== 'post'}
      />
    </div>
  );
}
