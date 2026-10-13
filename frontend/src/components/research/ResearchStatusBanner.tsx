import type { StatusMessage } from '@/hooks/useResearch';

interface ResearchStatusBannerProps {
  status: StatusMessage;
  researching: boolean;
  progress: number;
}

export function ResearchStatusBanner({ status, researching, progress }: ResearchStatusBannerProps) {
  const toneClass = status.tone === 'error'
    ? 'bg-red-50 text-red-800 border-red-200 dark:bg-red-900/20'
    : 'bg-blue-50 text-blue-800 border-blue-200 dark:bg-blue-900/20';
  return (
    <div aria-live="polite" className={`p-4 rounded-xl text-sm font-medium border shadow-sm ${toneClass}`}>
      <div className="flex justify-between mb-2">
        <span>{status.text}</span>
        {researching && <span>{progress}%</span>}
      </div>
      {researching && (
        <div className="w-full bg-blue-200/50 rounded-full h-2 overflow-hidden">
          <div
            className="bg-blue-600 h-2 rounded-full transition-all duration-500 ease-out"
            style={{ width: `${progress}%` }}
          />
        </div>
      )}
    </div>
  );
}
