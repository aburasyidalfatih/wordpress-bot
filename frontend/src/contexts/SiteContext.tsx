import React, { createContext, useContext, useState, useEffect } from 'react';
import type { ReactNode } from 'react';

export interface WordPressSite {
  id: number;
  site_name: string;
  wordpress_url: string;
  wordpress_username: string;
  is_active: boolean;

  schedule_hours: string;
  timezone?: string;
  auto_post: boolean;
  categories: any[];
  selected_categories: any[];
  telegram_enabled: boolean;
  telegram_bot_token: string;
  telegram_chat_id: string;
  facebook_enabled: boolean;
  twitter_enabled: boolean;
  threads_enabled: boolean;

  article_prompt: string | null;
  image_prompt: string | null;
  wordpress_password?: string;
  telegram_post_to_channel?: boolean;
  telegram_channel_id?: string;
  facebook_page_id?: string;
  facebook_access_token?: string;
  twitter_api_key?: string;
  twitter_api_secret?: string;
  twitter_access_token?: string;
  twitter_access_secret?: string;
  threads_user_id?: string;
  threads_access_token?: string;
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

  const fetchSites = async () => {
    try {
      const token = localStorage.getItem('token');
      if (!token) {
        setLoading(false);
        return;
      }
      
      const response = await fetch('/api/sites', {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });
      const data = await response.json();
      if (data.success && data.sites) {
        setSites(data.sites);
        
        // If we don't have a selected site, or the selected site is no longer in the list
        if (!selectedSiteId && data.sites.length > 0) {
          setSelectedSiteId(data.sites[0].id);
        } else if (selectedSiteId && !data.sites.find((s: WordPressSite) => s.id === selectedSiteId)) {
          setSelectedSiteId(data.sites.length > 0 ? data.sites[0].id : null);
        }
      }
    } catch (error) {
      console.error('Failed to fetch sites:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSites();
  }, []);

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
