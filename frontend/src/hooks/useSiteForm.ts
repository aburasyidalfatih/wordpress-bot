import { useState } from 'react';
import { toast } from 'sonner';
import { apiFetch, NETWORK_ERROR } from '@/lib/api';
import { useSiteContext } from '@/hooks/useSiteContext';
import type { SiteCategory, SiteDraft } from '@/lib/types';

// Fields the backend derives itself. Prompts are owned by the Prompts page
// (/api/save-prompts); never send the cached copy here or it would overwrite
// newer prompts. has_* flags and the Search Console status are read-only too.
const READ_ONLY_SITE_FIELDS = new Set([
  'id',
  'article_prompt',
  'image_prompt',
  'gsc_connected',
  'gsc_permission_level',
  'gsc_connected_at',
  'gsc_last_synced_at',
  'gsc_last_error',
]);

export const NEW_SITE_DEFAULTS: SiteDraft = {
  site_name: '',
  wordpress_url: '',
  wordpress_username: '',
  wordpress_password: '',
  is_active: true,
  auto_post: false,
  schedule_hours: '0,6,12,18',
  timezone: 'Asia/Jakarta',
  language: 'id',
  telegram_enabled: false,
  facebook_enabled: false,
  twitter_enabled: false,
  threads_enabled: false,
  gsc_client_id: '',
  gsc_client_secret: '',
};

function buildSitePayload(site: SiteDraft): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(site)) {
    if (READ_ONLY_SITE_FIELDS.has(key) || key.startsWith('has_')) continue;
    payload[key] = value;
  }
  return payload;
}

/** State and actions of the website create/edit form. */
export function useSiteForm(initialSite: SiteDraft, onClose: () => void) {
  const { fetchSites, setSelectedSiteId } = useSiteContext();
  const [site, setSite] = useState<SiteDraft>(initialSite);
  const [saving, setSaving] = useState(false);

  const updateSite = (patch: SiteDraft) => setSite(prev => ({ ...prev, ...patch }));

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value, type, checked } = e.target;
    updateSite({ [name]: type === 'checkbox' ? checked : value });
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const res = await apiFetch(site.id ? `/api/sites/${site.id}` : '/api/sites', {
        method: site.id ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildSitePayload(site)),
      });
      const data = await res.json();
      if (res.ok && data.success) {
        toast.success(`Website berhasil ${site.id ? 'diperbarui' : 'dibuat'}.`);
        await fetchSites();
        if (!site.id && data.site_id) {
          setSelectedSiteId(data.site_id);
        }
        onClose();
      } else {
        toast.error(data.error || 'Gagal menyimpan website.');
      }
    } catch {
      toast.error(NETWORK_ERROR);
    } finally {
      setSaving(false);
    }
  };

  const deleteSite = async (id: number) => {
    try {
      const res = await apiFetch(`/api/sites/${id}`, { method: 'DELETE' });
      if (res.ok) {
        toast.success('Website berhasil dihapus.');
        // fetchSites() re-selects another site when the selected one no longer exists.
        await fetchSites();
        onClose();
      } else {
        const data = await res.json();
        toast.error(data.error || 'Gagal menghapus website.');
      }
    } catch {
      toast.error(NETWORK_ERROR);
    }
  };

  const fetchCategories = async () => {
    if (!site.id) {
      toast.error('Simpan website terlebih dahulu sebelum mengambil kategori.');
      return;
    }
    toast.info('Mengambil kategori...');
    try {
      const res = await apiFetch(`/api/sites/${site.id}/fetch-categories`, { method: 'POST' });
      const data = await res.json();
      if (res.ok && data.success) {
        const fetched: SiteCategory[] = data.categories || [];
        setSite(prev => {
          // AI hints typed in this form but not saved yet win over the stored ones.
          const newCategories = fetched.map(cat => {
            const local = (prev.categories || []).find(c => c.id === cat.id);
            return local && local.ai_hint !== undefined ? { ...cat, ai_hint: local.ai_hint } : cat;
          });
          const stillSelected = (prev.selected_categories || []).filter(sel =>
            newCategories.some(cat => cat.id === sel.id)
          );
          return {
            ...prev,
            categories: newCategories,
            selected_categories: stillSelected.length === 0 ? newCategories : stillSelected,
          };
        });
        toast.success('Kategori berhasil diambil.');
        fetchSites(); // refresh global state
      } else {
        toast.error(data.error || 'Gagal mengambil kategori.');
      }
    } catch {
      toast.error(NETWORK_ERROR);
    }
  };

  return { site, updateSite, handleChange, saving, handleSave, deleteSite, fetchCategories };
}
