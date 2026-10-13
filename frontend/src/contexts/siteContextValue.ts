import { createContext } from 'react';
import type { WordPressSite } from '@/lib/types';

interface SiteContextValue {
  sites: WordPressSite[];
  selectedSiteId: number | null;
  selectedSite: WordPressSite | null;
  setSelectedSiteId: (id: number | null) => void;
  fetchSites: () => Promise<void>;
  loading: boolean;
}

export const SiteContext = createContext<SiteContextValue | undefined>(undefined);
