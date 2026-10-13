import type { SiteDraft } from '@/lib/types';

export interface SiteTabProps {
  site: SiteDraft;
  updateSite: (patch: SiteDraft) => void;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
}

export const SITE_TABS = [
  { id: 'wordpress', label: 'WordPress' },
  { id: 'automation', label: 'Otomasi' },
  { id: 'search-console', label: 'Search Console' },
  { id: 'telegram', label: 'Telegram' },
  { id: 'facebook', label: 'Facebook' },
  { id: 'pinterest', label: 'Pinterest' },
  { id: 'twitter', label: 'Twitter' },
  { id: 'threads', label: 'Threads' },
] as const;

export type SiteTabId = (typeof SITE_TABS)[number]['id'];

export const SAVED_SECRET_PLACEHOLDER = 'Sudah tersimpan. Isi untuk mengganti.';
