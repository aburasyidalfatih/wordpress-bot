import React, { createContext, useContext, useState, useEffect, useRef, useCallback } from 'react';
import type { ReactNode } from 'react';

export interface SiteCategory {
  id: number;
  name: string;
  description?: string;
  count?: number;
}

export interface WordPressSite {
  id: number;
  site_name: string;
  wordpress_url: string;
  wordpress_username: string;
  is_active: boolean;

  schedule_hours: string;
  timezone?: string;
  language?: string;
  auto_post: boolean;
  categories: SiteCategory[];
  selected_categories: SiteCategory[];
  telegram_enabled: boolean;
  telegram_bot_token: string;
  telegram_chat_id: string;
  facebook_enabled: boolean;
  twitter_enabled: boolean;
  threads_enabled: boolean;

  article_prompt: string | null;
  image_prompt: string | null;
  wordpress_password?: string;
  has_wordpress_password?: boolean;
  telegram_post_to_channel?: boolean;
  telegram_channel_id?: string;
  has_telegram_bot_token?: boolean;
  facebook_page_id?: string;
  facebook_access_token?: string;
  has_facebook_access_token?: boolean;
  twitter_api_key?: string;
  twitter_api_secret?: string;
  twitter_access_token?: string;
  twitter_access_secret?: string;
  has_twitter_api_key?: boolean;
  has_twitter_api_secret?: boolean;
  has_twitter_access_token?: boolean;
  has_twitter_access_secret?: boolean;
  threads_user_id?: string;
  threads_access_token?: string;
  has_threads_access_token?: boolean;
}

interface SiteContextType {
  sites: WordPressSite[];
  selectedSiteId: number | null;
  selectedSite: WordPressSite | null;
  setSelectedSiteId: (id: number | null) => void;
  fetchSites: () => Promise<void>;
  loading: boolean;
}

const SiteContext = createContext<SiteContextType | undefined>(undefined);

export const SiteProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [sites, setSites] = useState<WordPressSite[]>([]);
  const [selectedSiteId, setSelectedSiteId] = useState<number | null>(() => {
    const saved = localStorage.getItem('selectedSiteId');
    return saved ? parseInt(saved, 10) : null;
  });
  const [loading, setLoading] = useState(true);

  const selectedSiteIdRef = useRef(selectedSiteId);
  useEffect(() => { selectedSiteIdRef.current = selectedSiteId; }, [selectedSiteId]);

  const fetchSites = useCallback(async (signal?: AbortSignal) => {
    try {
      const token = localStorage.getItem('token');
      if (!token) {
        setLoading(false);
        return;
      }
      
      const response = await fetch('/api/sites', {
        headers: {
          'Authorization': `Bearer ${token}`
        },
        credentials: 'include',
        signal
      });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const data = await response.json();
      if (data.success && data.sites) {
        setSites(data.sites);
        
        const currentSelectedId = selectedSiteIdRef.current;
        // If we don't have a selected site, or the selected site is no longer in the list
        if (!currentSelectedId && data.sites.length > 0) {
          setSelectedSiteId(data.sites[0].id);
        } else if (currentSelectedId && !data.sites.find((s: WordPressSite) => s.id === currentSelectedId)) {
          setSelectedSiteId(data.sites.length > 0 ? data.sites[0].id : null);
        }
      }
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === 'AbortError') return;
      console.error('Failed to fetch sites:', error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    fetchSites(controller.signal);
    return () => controller.abort();
  }, [fetchSites]);

  useEffect(() => {
    if (selectedSiteId !== null) {
      localStorage.setItem('selectedSiteId', selectedSiteId.toString());
    } else {
      localStorage.removeItem('selectedSiteId');
    }
  }, [selectedSiteId]);

  const selectedSite = sites.find(s => s.id === selectedSiteId) || null;

  return (
    <SiteContext.Provider value={{ sites, selectedSiteId, selectedSite, setSelectedSiteId, fetchSites, loading }}>
      {children}
    </SiteContext.Provider>
  );
};

export const useSiteContext = () => {
  const context = useContext(SiteContext);
  if (context === undefined) {
    throw new Error('useSiteContext must be used within a SiteProvider');
  }
  return context;
};
