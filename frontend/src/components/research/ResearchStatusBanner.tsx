import { X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { StatusMessage } from '@/hooks/useResearch';

const TONE_CLASS: Record<StatusMessage['tone'], string> = {
  info: 'bg-blue-50 text-blue-800 border-blue-200 dark:bg-blue-900/20',
  success: 'bg-emerald-50 text-emerald-800 border-emerald-200 dark:bg-emerald-900/20',
  warning: 'bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-900/20',
  error: 'bg-red-50 text-red-800 border-red-200 dark:bg-red-900/20',
};

interface ResearchStatusBannerProps {
  status: StatusMessage;
  /** Show the progress bar (a research job or bulk title generation runs). */
  showProgress: boolean;
  progress: number;
  /** When set, a cancel button is shown (bulk title generation). */
  onCancel?: () => void;
}

export function ResearchStatusBanner({ status, showProgress, progress, onCancel }: ResearchStatusBannerProps) {
  return (
    <div
      role={status.tone === 'error' ? 'alert' : 'status'}
      aria-live={status.tone === 'error' ? 'assertive' : 'polite'}
      className={`p-4 rounded-xl text-sm font-medium border shadow-sm ${TONE_CLASS[status.tone]}`}
    >
      <div className={`flex items-center justify-between gap-3 ${showProgress ? 'mb-2' : ''}`}>
        <span>{status.text}</span>
        <div className="flex shrink-0 items-center gap-3">
          {showProgress && <span>{progress}%</span>}
          {onCancel && (
            <Button size="sm" variant="outline" onClick={onCancel} className="gap-1 bg-background/70">
              <X className="h-3.5 w-3.5" /> Batalkan
            </Button>
          )}
        </div>
      </div>
      {showProgress && (
        <div
          role="progressbar"
          aria-label="Progres"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progress}
          className="w-full bg-blue-200/50 rounded-full h-2 overflow-hidden"
        >
          <div
            className="bg-blue-600 h-2 rounded-full transition-all duration-500 ease-out"
            style={{ width: `${progress}%` }}
          />
        </div>
      )}
    </div>
  );
}
