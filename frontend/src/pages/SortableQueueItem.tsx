import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Trash2, GripVertical, Pencil, Play, Eye, Loader2 } from 'lucide-react';
import { useEffect, useState } from 'react';

export function SortableQueueItem({ item, handleDelete, handleEdit, handlePostNow }: { item: any, handleDelete: (id: number) => void, handleEdit: (item: any) => void, handlePostNow: (id: number) => void }) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: item.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    zIndex: isDragging ? 10 : 1,
    position: 'relative' as const,
  };

  const [progress, setProgress] = useState(0);
  useEffect(() => {
    if (item.status === 'posting') {
      const timer = setTimeout(() => setProgress(95), 100);
      return () => clearTimeout(timer);
    } else {
      setProgress(0);
    }
  }, [item.status]);

  return (
    <div ref={setNodeRef} style={style} className={`transition-opacity ${isDragging ? 'opacity-50' : 'opacity-100'}`}>
      <Card className={`hover:border-primary/50 transition-all duration-300 bg-card ${item.status === 'posting' ? 'border-blue-500/60 shadow-lg shadow-blue-500/5 ring-1 ring-blue-500/15 bg-gradient-to-r from-card via-card to-blue-500/[0.02]' : ''}`}>
        <CardContent className="p-0 flex items-stretch">
          <div 
            {...attributes} 
            {...listeners} 
            className="w-12 border-r flex items-center justify-center cursor-grab active:cursor-grabbing bg-muted/20 hover:bg-muted/50 transition-colors"
          >
            <GripVertical className="h-5 w-5 text-muted-foreground" />
          </div>
          
          <div className="p-6 flex flex-1 flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
            <div>
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-500/15">
                  {item.category}
                </span>
                <span className={`text-xs font-semibold px-2.5 py-0.5 rounded-full border shadow-sm transition-all ${
                  item.status === 'pending' 
                    ? 'bg-amber-500/10 border-amber-500/20 text-amber-600 dark:text-amber-400' 
                    : item.status === 'posting' 
                    ? 'bg-blue-500/10 border-blue-500/30 text-blue-600 dark:text-blue-400 animate-pulse' 
                    : 'bg-green-500/10 border-green-500/20 text-green-600 dark:text-green-400'
                }`}>
                  {item.status === 'posting' ? 'PROCESSING...' : item.status.toUpperCase()}
                </span>
              </div>
              <h3 className="font-semibold text-lg">{item.title}</h3>
              {item.target_keywords && (
                <p className="text-sm text-muted-foreground mt-1">
                  <span className="font-medium text-foreground">Keywords:</span> {item.target_keywords}
                </p>
              )}
              <p className="text-xs text-muted-foreground mt-2">Added: {item.created_at}</p>

              
              {item.status === 'posting' && (
                <div className="mt-4 max-w-sm">
                  <div className="flex justify-between text-xs text-blue-600 mb-1">
                    <span className="flex items-center gap-1"><Loader2 className="h-3 w-3 animate-spin" /> Generating Article & Image...</span>
                    <span>Wait ~30s</span>
                  </div>
                  <div className="w-full bg-blue-100 rounded-full h-2.5 overflow-hidden">
                    <div className="bg-blue-600 h-2.5 rounded-full transition-all ease-out" style={{ width: `${progress}%`, transitionDuration: '30000ms' }}></div>
                  </div>
                </div>
              )}
            </div>
            
            <div className="flex gap-2">
              {item.status === 'posted' && item.post_url && (
                <Button variant="outline" size="icon" onClick={() => window.open(item.post_url, '_blank')} className="text-purple-600 hover:text-purple-700 hover:bg-purple-50 z-20" title="View Post">
                  <Eye className="h-4 w-4" />
                </Button>
              )}
              <Button variant="outline" size="icon" onClick={() => handlePostNow(item.id)} className="text-green-600 hover:text-green-700 hover:bg-green-50 z-20" title={item.status === 'posting' ? "Retry Post" : "Post Now"}>
                <Play className="h-4 w-4" />
              </Button>
              <Button variant="outline" size="icon" onClick={() => handleEdit(item)} className="text-blue-600 hover:text-blue-700 hover:bg-blue-50 z-20" title="Edit">
                <Pencil className="h-4 w-4" />
              </Button>
              <Button variant="outline" size="icon" onClick={() => handleDelete(item.id)} className="text-red-500 hover:text-red-600 hover:bg-red-50 z-20" title="Delete">
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
