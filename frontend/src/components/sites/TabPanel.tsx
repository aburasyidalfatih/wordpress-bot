import type { ReactNode } from 'react';

export function TabPanel({ id, className = 'space-y-4', children }: { id: string; className?: string; children: ReactNode }) {
  return (
    <div id={`panel-${id}`} role="tabpanel" aria-labelledby={`tab-${id}`} className={`${className} animate-in fade-in slide-in-from-right-4 duration-300`}>
      {children}
    </div>
  );
}
