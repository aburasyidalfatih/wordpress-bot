import { RefreshCw, SearchCheck, Link2, Unlink } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { useSearchConsole } from '@/hooks/useSearchConsole';
import { TabPanel } from './TabPanel';
import { SAVED_SECRET_PLACEHOLDER, type SiteTabProps } from './siteForm';

type SearchConsoleTabProps = Omit<SiteTabProps, 'updateSite'> & {
  /** Owned by the editor so the property list survives switching tabs. */
  gsc: ReturnType<typeof useSearchConsole>;
};

export function SearchConsoleTab({ site, onChange, gsc }: SearchConsoleTabProps) {
  const canConnect = !!site.id && !!site.gsc_client_id && (!!site.has_gsc_client_secret || !!site.gsc_client_secret);

  return (
    <TabPanel id="search-console" className="space-y-5">
      <div className="rounded-xl border bg-muted/20 p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 font-semibold"><SearchCheck className="h-5 w-5 text-primary" /> Google Search Console</div>
            <p className="mt-1 text-sm text-muted-foreground">Akses read-only untuk query, impression, klik, CTR, dan posisi pencarian.</p>
          </div>
          <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${site.gsc_connected ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-border bg-background text-muted-foreground'}`}>
            {site.gsc_connected ? 'Terhubung' : 'Belum terhubung'}
          </span>
        </div>
      </div>

      <div className="grid gap-4 rounded-xl border p-4">
        <div className="space-y-2">
          <Label htmlFor="gsc_client_id">Google OAuth Client ID</Label>
          <Input
            id="gsc_client_id"
            name="gsc_client_id"
            value={site.gsc_client_id || ''}
            onChange={onChange}
            placeholder="000000000000-xxxxx.apps.googleusercontent.com"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="gsc_client_secret">Google OAuth Client Secret</Label>
          <Input
            id="gsc_client_secret"
            name="gsc_client_secret"
            type="password"
            value={site.gsc_client_secret || ''}
            onChange={onChange}
            placeholder={site.has_gsc_client_secret ? SAVED_SECRET_PLACEHOLDER : 'GOCSPX-...'}
          />
          <p className="text-xs text-muted-foreground">Client Secret disimpan terenkripsi dan tidak pernah dikirim kembali ke browser.</p>
        </div>
        <div className="space-y-2">
          <Label>Authorized redirect URI</Label>
          <div className="rounded-md border bg-muted/30 px-3 py-2 font-mono text-xs break-all">
            {`${window.location.origin}/api/search-console/callback`}
          </div>
          <p className="text-xs text-muted-foreground">Salin URI ini ke Google Cloud → OAuth Client → Authorized redirect URIs.</p>
        </div>
        {!site.id && (
          <p className="rounded-md border border-blue-200 bg-blue-50 p-3 text-xs text-blue-700">Simpan website terlebih dahulu, lalu buka kembali tab ini untuk menghubungkan akun Google.</p>
        )}
      </div>

      {!site.gsc_connected ? (
        <Button type="button" onClick={gsc.connect} disabled={gsc.busy || !canConnect} className="gap-2">
          <Link2 className="h-4 w-4" /> {gsc.busy ? 'Menghubungkan...' : 'Hubungkan Google Search Console'}
        </Button>
      ) : (
        <div className="space-y-4">
          <div className="space-y-2">
            <Label>Property aktif</Label>
            <select
              value={site.gsc_property_url || ''}
              onChange={(event) => gsc.selectProperty(event.target.value)}
              disabled={gsc.busy || gsc.properties.length === 0}
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            >
              <option value="">{site.gsc_property_url || 'Ambil daftar property terlebih dahulu'}</option>
              {gsc.properties.map(property => (
                <option key={property.site_url} value={property.site_url}>{property.site_url} ({property.permission_level})</option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground">Terpilih: {site.gsc_property_url || 'Belum dipilih otomatis'}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" onClick={gsc.loadProperties} disabled={gsc.busy}>
              <RefreshCw className="mr-2 h-4 w-4" /> Ambil Property
            </Button>
            <Button type="button" onClick={gsc.sync} disabled={gsc.busy || !site.gsc_property_url}>
              <SearchCheck className="mr-2 h-4 w-4" /> Sinkronkan 56 Hari
            </Button>
            <Button type="button" variant="ghost" onClick={gsc.disconnect} disabled={gsc.busy} className="text-destructive">
              <Unlink className="mr-2 h-4 w-4" /> Putuskan
            </Button>
          </div>
          {site.gsc_last_synced_at && <p className="text-xs text-muted-foreground">Sinkron terakhir: {new Date(site.gsc_last_synced_at).toLocaleString('id-ID')}</p>}
          {site.gsc_last_error && <p className="rounded-md border border-red-200 bg-red-50 p-3 text-xs text-red-700">{site.gsc_last_error}</p>}
        </div>
      )}
    </TabPanel>
  );
}
