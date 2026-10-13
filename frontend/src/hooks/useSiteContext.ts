import { useContext } from 'react';
import { SiteContext } from '@/contexts/siteContextValue';

export function useSiteContext() {
  const context = useContext(SiteContext);
  if (context === undefined) {
    throw new Error('useSiteContext must be used within a SiteProvider');
  }
  return context;
}
