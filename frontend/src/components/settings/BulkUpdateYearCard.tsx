import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { apiFetch, isAbortError, NETWORK_ERROR } from '@/lib/api';
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { WordPressSite } from '@/lib/types';

/** Admin tool: replace a year with another in the titles and content of all articles of a site. */
export function BulkUpdateYearCard() {
  const [siteId, setSiteId] = useState('');
  const [fromYear, setFromYear] = useState('2026');
  const [toYear, setToYear] = useState('2027');
  const [loading, setLoading] = useState(false);
  const [sites, setSites] = useState<WordPressSite[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    apiFetch('/api/sites', { signal: controller.signal })
      .then(res => res.json())
      .then(data => {
        if (!data.success) return;
        const list: WordPressSite[] = data.sites || [];
        setSites(list);
        if (list.length > 0) setSiteId(list[0].id.toString());
      })
      .catch(err => { if (!isAbortError(err) && import.meta.env.DEV) console.error(err); });
    return () => controller.abort();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!siteId || !fromYear || !toYear) {
      toast.error('Semua kolom wajib diisi.');
      return;
    }
    setLoading(true);
    try {
      const res = await apiFetch('/api/admin/bulk_update_year', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ site_id: parseInt(siteId), from_year: fromYear, to_year: toYear }),
      });
      const data = await res.json();
      if (data.success) {
        toast.success(data.message || 'Pembaruan massal berjalan di latar belakang.');
      } else {
        toast.error(data.error || 'Gagal memulai pembaruan massal.');
      }
    } catch {
      toast.error(NETWORK_ERROR);
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <Card className="border-border/50 shadow-md h-full">
        <CardHeader>
          <CardTitle>Perbarui Tahun SEO Massal (Admin)</CardTitle>
          <CardDescription>Ganti tahun tertentu di judul dan isi semua artikel dengan tahun yang baru.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 pb-8">
          <div className="space-y-2">
            <Label htmlFor="admin_site_id">Pilih Website</Label>
            <select
              id="admin_site_id"
              value={siteId}
              onChange={(e) => setSiteId(e.target.value)}
              className="flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <option value="" disabled>Pilih website</option>
              {sites.map(site => (
                <option key={site.id} value={site.id.toString()}>{site.site_name}</option>
              ))}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="admin_from_year">Dari Tahun</Label>
              <Input id="admin_from_year" value={fromYear} onChange={e => setFromYear(e.target.value)} placeholder="mis. 2026" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="admin_to_year">Ke Tahun</Label>
              <Input id="admin_to_year" value={toYear} onChange={e => setToYear(e.target.value)} placeholder="mis. 2027" />
            </div>
          </div>
        </CardContent>
        <CardFooter className="bg-muted/50 py-4 mt-auto">
          <Button type="submit" disabled={loading} className="w-full">
            {loading ? 'Memulai...' : 'Mulai Pembaruan Massal'}
          </Button>
        </CardFooter>
      </Card>
    </form>
  );
}
