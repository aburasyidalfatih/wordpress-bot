import { toast } from 'sonner';
import { fetchJson, isAbortError } from '@/lib/api';
import { useSiteContext } from '@/hooks/useSiteContext';
import { useApiResource } from '@/hooks/useApiResource';
import EmptyState from '@/components/EmptyState';
import { PromptsForm } from '@/components/prompts/PromptsForm';
import type { PromptsData } from '@/lib/types';

export default function Prompts() {
  const { selectedSiteId } = useSiteContext();
  const { data, loading } = useApiResource<PromptsData>(
    selectedSiteId ? `/api/prompts?site_id=${selectedSiteId}` : null,
    signal => fetchJson<PromptsData>(`/api/prompts?site_id=${selectedSiteId}`, { signal }, 'Gagal memuat prompt')
      .catch((error: unknown) => {
        if (!isAbortError(error)) toast.error(error instanceof Error ? error.message : 'Gagal memuat prompt.');
        throw error;
      }),
  );

  if (!selectedSiteId) return <EmptyState title="Pengaturan Prompt AI" description="Pilih salah satu website Anda dari menu dropdown di kanan atas untuk menyesuaikan instruksi penulisan artikel dan gambar AI." />;
  if (loading) return <div className="p-8">Memuat prompt...</div>;

  // Remount per site so the editable prompts start from that site's saved values.
  return <PromptsForm key={selectedSiteId} siteId={selectedSiteId} data={data} />;
}
