import { useEffect, useState, useRef } from 'react';
import { apiFetch } from '../lib/api';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { RefreshCw, Plus, LayoutList, Eye, AlertCircle } from 'lucide-react';
import { DndContext, closestCenter, KeyboardSensor, PointerSensor, useSensor, useSensors } from '@dnd-kit/core';
import { arrayMove, SortableContext, sortableKeyboardCoordinates, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { SortableQueueItem } from './SortableQueueItem';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { useSiteContext } from '@/contexts/SiteContext';

export default function Queue() {
  const { selectedSiteId, sites } = useSiteContext();
  const [items, setItems] = useState<any[]>([]);
  const [historyItems, setHistoryItems] = useState<any[]>([]);
  const [activeTab, setActiveTab] = useState<'queue' | 'history'>('queue');
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newCategory, setNewCategory] = useState('');
  const [editingItem, setEditingItem] = useState<any>(null);
  const [editTitle, setEditTitle] = useState('');
  const [editKeywords, setEditKeywords] = useState('');
  const [regeneratingIds, setRegeneratingIds] = useState<Record<number, boolean>>({});
  const pollingDelayRef = useRef(3000);
  const [confirmAction, setConfirmAction] = useState<{type: 'delete' | 'post', id: number} | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const handleDragEnd = async (event: any) => {
    const { active, over } = event;
    
    if (active.id !== over.id) {
      setItems((items) => {
        const oldIndex = items.findIndex((i) => i.id === active.id);
        const newIndex = items.findIndex((i) => i.id === over.id);
        const newItems = arrayMove(items, oldIndex, newIndex);
        
        // Save the new order to the backend
        apiFetch('/api/queue/reorder', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ids: newItems.map((i) => i.id) })
        }).catch(err => console.error('Failed to save order:', err));
        
        return newItems;
      });
    }
  };

  const loadQueue = (silent = false) => {
    if (!selectedSiteId) {
      setLoading(false);
      return;
    }
    if (!silent) setLoading(true);
    apiFetch(`/api/queue?site_id=${selectedSiteId}`)
      .then(res => {
        if (!res.ok) throw new Error('API Error');
        return res.json();
      })
      .then(d => {
        if (d.success) {
          setItems(d.queue || []);
          setHistoryItems(d.history || []);
        } else {
          console.error('Queue API failed:', d.error);
        }
      })
      .catch(e => {
        console.error('Failed to load queue/history:', e);
      })
      .finally(() => {
        if (!silent) setLoading(false);
      });
  };

  useEffect(() => {
    loadQueue();
  }, []);

  useEffect(() => {
    const hasPosting = items.some(i => i.status === 'posting');
    const hasRegenerating = Object.values(regeneratingIds).some(Boolean);
    
    let timeoutId: ReturnType<typeof setTimeout>;
    
    if (hasPosting || hasRegenerating) {
      timeoutId = setTimeout(() => {
        loadQueue(true);
        // Exponential backoff, max 15 seconds
        pollingDelayRef.current = Math.min(pollingDelayRef.current * 1.5, 15000);
      }, pollingDelayRef.current);
    } else {
      // Reset delay when no active processes
      pollingDelayRef.current = 3000;
    }
    
    return () => clearTimeout(timeoutId);
  }, [items, regeneratingIds]);

  useEffect(() => {
    loadQueue();
    // Default category to the first one available
    const activeSite = sites.find(s => s.id === selectedSiteId);
    if (activeSite?.categories?.length && !newCategory) {
      setNewCategory(activeSite.categories[0].name);
    }
  }, [selectedSiteId, sites]);

  const handleDelete = (id: number) => {
    setConfirmAction({ type: 'delete', id });
  };

  const executeDelete = async (id: number) => {
    try {
      await apiFetch('/api/queue', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id })
      });
      loadQueue();
    } catch (e) {
      console.error(e);
    } finally {
      setConfirmAction(null);
    }
  };

  const handleRegenerateImage = async (logId: number) => {
    setRegeneratingIds(prev => ({ ...prev, [logId]: true }));
    try {
      const res = await apiFetch(`/api/queue/history/regenerate-image/${logId}`, {
        method: 'POST'
      });
      const data = await res.json();
      if (!data.success) {
        toast.error('Failed: ' + (data.error || 'Server error'));
        setRegeneratingIds(prev => ({ ...prev, [logId]: false }));
      }
      // If success, leave it true so it keeps spinning. The polling will update the list and remove the button when done.
      if (data.success) {
        setTimeout(() => {
          setRegeneratingIds(prev => ({ ...prev, [logId]: false }));
        }, 60000);
      }
    } catch (e) {
      console.error(e);
      toast.error('Network error');
      setRegeneratingIds(prev => ({ ...prev, [logId]: false }));
    }
  };

  const handleManualAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle || !newCategory) return;
    setAdding(true);
    try {
      const res = await apiFetch('/api/queue', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          site_id: selectedSiteId,
          title: newTitle,
          category: newCategory,
          target_keywords: ''
        })
      });
      const data = await res.json();
      if (data.success) {
        toast.success('Artikel berhasil ditambahkan ke antrian!');
        setNewTitle('');
        loadQueue();
      } else {
        toast.error('Gagal menambahkan ke antrian: ' + (data.error || 'Terjadi kesalahan pada peladen.'));
      }
    } catch (e) {
      console.error(e);
      toast.error('Galat jaringan! Pastikan Anda sudah memuat ulang (Refresh) halaman.');
    } finally {
      setAdding(false);
    }
  };

  const handlePostNow = (id: number) => {
    setConfirmAction({ type: 'post', id });
  };

  const executePostNow = async (id: number) => {
    // Optimistic UI update to show progress bar instantly
    setItems(current => current.map(item => 
      item.id === id ? { ...item, status: 'posting' } : item
    ));

    try {
      const res = await apiFetch(`/api/queue/post/${id}`, { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        toast.success('Artikel sedang diproses!');
        loadQueue(true);
      } else {
        toast.error('Failed to post item: ' + (data.error || 'Server error'));
        loadQueue(true);
      }
    } catch (e) {
      console.error(e);
      toast.error('Network error');
      loadQueue(true);
    } finally {
      setConfirmAction(null);
    }
  };

  const handleEdit = (item: any) => {
    setEditingItem(item);
    setEditTitle(item.title);
    setEditKeywords(item.target_keywords || '');
  };

  const handleSaveEdit = async () => {
    if (!editingItem) return;
    try {
      const res = await apiFetch(`/api/queue/edit/${editingItem.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: editTitle, target_keywords: editKeywords })
      });
      const data = await res.json();
      if (data.success) {
        toast.success('Perubahan berhasil disimpan!');
        setEditingItem(null);
        loadQueue(true);
      } else {
        toast.error('Failed to save edit: ' + (data.error || 'Server error'));
      }
    } catch (e) {
      console.error(e);
      toast.error('Network error');
    }
  };


  if (!selectedSiteId) return <div className="p-8 text-center text-muted-foreground mt-20">Please select a website from the top bar to view its queue.</div>;
  if (loading) return <div className="p-8 flex items-center justify-center">
    <RefreshCw className="h-8 w-8 animate-spin text-primary" />
  </div>;

  const activeSite = sites.find(s => s.id === selectedSiteId);
  const availableCategories = activeSite?.categories || [];

  const pendingItems = items.filter(i => i.status !== 'posted' && i.status !== 'failed');

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-primary to-indigo-600 dark:from-primary dark:to-indigo-400 bg-clip-text text-transparent flex items-center gap-2">
          <LayoutList className="h-8 w-8 text-primary" /> Content Queue
        </h1>
        <p className="text-muted-foreground mt-1">Manage AI-generated titles and manual ideas waiting to be published.</p>
      </div>

      <Card className="border-border/50 shadow-md">
        <CardHeader>
          <CardTitle>Add Custom Title</CardTitle>
          <CardDescription>Manually insert an idea into the publishing queue.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleManualAdd} className="flex gap-4 items-center">
            <select
              value={newCategory}
              onChange={e => setNewCategory(e.target.value)}
              className="flex h-10 w-[200px] items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {availableCategories.length === 0 ? (
                <option value="" disabled>No categories found</option>
              ) : (
                availableCategories.map((cat: any) => (
                  <option key={cat.id} value={cat.name}>{cat.name}</option>
                ))
              )}
            </select>
            <Input 
              placeholder="Article Title..." 
              value={newTitle} 
              onChange={e => setNewTitle(e.target.value)} 
              className="flex-1"
            />
            <Button type="submit" disabled={adding || !newTitle || !newCategory}>
              <Plus className="h-4 w-4 mr-2" />
              Add to Queue
            </Button>
          </form>
        </CardContent>
      </Card>

      <div className="flex border-b border-muted">
        <button 
          className={`px-4 py-2 border-b-2 font-medium text-sm transition-colors ${activeTab === 'queue' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}`}
          onClick={() => setActiveTab('queue')}
        >
          Pending / Draft
        </button>
        <button 
          className={`px-4 py-2 border-b-2 font-medium text-sm transition-colors ${activeTab === 'history' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}`}
          onClick={() => setActiveTab('history')}
        >
          History
        </button>
      </div>

      {activeTab === 'queue' ? (
        <div className="grid gap-4">
          {pendingItems.length === 0 ? (
            <div className="text-center p-8 text-muted-foreground bg-muted/50 rounded-xl">
              No items in queue. Go to Research to generate some!
            </div>
          ) : (
            <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
              <SortableContext items={pendingItems.map(i => i.id)} strategy={verticalListSortingStrategy}>
                {pendingItems.map(item => (
                  <SortableQueueItem key={item.id} item={item} handleDelete={handleDelete} handleEdit={handleEdit} handlePostNow={handlePostNow} />
                ))}
              </SortableContext>
            </DndContext>
          )}
        </div>
      ) : (
        <div className="grid gap-4">
          {historyItems.length === 0 ? (
            <div className="text-center p-8 text-muted-foreground bg-muted/50 rounded-xl">
              No history found.
            </div>
          ) : (
            historyItems.map(item => (
              <Card key={item.id} className="bg-card">
                <CardContent className="p-6 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                  <div>
                    <div className="flex items-center gap-2 mb-1 flex-wrap">
                      <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-blue-100 text-blue-800 border border-blue-200">
                        {item.category}
                      </span>
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${item.success ? 'bg-green-100 text-green-800 border-green-200' : 'bg-red-100 text-red-800 border-red-200'}`}>
                        {item.success ? 'POSTED' : 'FAILED'}
                      </span>
                      {item.success && item.image_failed && (
                        <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 border border-amber-200 flex items-center gap-1">
                          <AlertCircle className="w-3 h-3" /> Image Failed
                        </span>
                      )}
                    </div>
                    <h3 className="font-semibold text-lg">{item.title}</h3>
                    <p className="text-xs text-muted-foreground mt-2">Posted: {new Date(item.timestamp).toLocaleString()}</p>
                    {item.success && item.image_failed && (
                        <p className="text-xs text-red-500 mt-1">{item.result}</p>
                    )}
                  </div>
                  
                  {item.success && item.post_url && (
                    <div className="flex gap-2">
                      {item.image_failed && (
                        <Button 
                          variant="outline" 
                          size="sm" 
                          className="text-amber-600 border-amber-200 hover:bg-amber-50"
                          disabled={regeneratingIds[item.id]}
                          onClick={() => handleRegenerateImage(item.id)}
                        >
                          {regeneratingIds[item.id] ? (
                            <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                          ) : (
                            <RefreshCw className="h-4 w-4 mr-2" />
                          )}
                          Regenerate Image
                        </Button>
                      )}
                      <Button variant="outline" size="icon" onClick={() => window.open(item.post_url, '_blank')} className="text-purple-600 hover:text-purple-700 hover:bg-purple-50 z-20" title="View Post">
                        <Eye className="h-4 w-4" />
                      </Button>
                    </div>
                  )}
                </CardContent>
              </Card>
            ))
          )}
        </div>
      )}

      {editingItem && (
        <div className="fixed inset-0 z-50 bg-background/80 backdrop-blur-sm flex items-center justify-center p-4">
          <Card className="w-full max-w-lg shadow-lg">
            <CardHeader>
              <CardTitle>Edit Queue Item</CardTitle>
              <CardDescription>Modify title and target keywords before posting.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">Title</label>
                <Input value={editTitle} onChange={e => setEditTitle(e.target.value)} />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Keywords</label>
                <Input value={editKeywords} onChange={e => setEditKeywords(e.target.value)} placeholder="Comma separated keywords" />
              </div>
              <div className="flex justify-end gap-2 pt-4">
                <Button variant="outline" onClick={() => setEditingItem(null)}>Cancel</Button>
                <Button onClick={handleSaveEdit}>Save Changes</Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      <AlertDialog open={!!confirmAction} onOpenChange={(open) => !open && setConfirmAction(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Are you absolutely sure?</AlertDialogTitle>
            <AlertDialogDescription>
              {confirmAction?.type === 'delete' 
                ? 'This action cannot be undone. This will permanently delete this title from the queue.' 
                : 'This will immediately process and post this item right now.'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => {
              if (confirmAction?.type === 'delete') {
                executeDelete(confirmAction.id);
              } else if (confirmAction?.type === 'post') {
                executePostNow(confirmAction.id);
              }
            }}>
              Continue
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

    </div>
  );
}
