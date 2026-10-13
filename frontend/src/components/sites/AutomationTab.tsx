import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { SettingToggleRow } from './SettingToggleRow';
import { TabPanel } from './TabPanel';
import type { SiteTabProps } from './siteForm';

const TIMEZONES = [
  { value: 'Asia/Jakarta', label: 'Asia/Jakarta (WIB, GMT+7)' },
  { value: 'Asia/Makassar', label: 'Asia/Makassar (WITA, GMT+8)' },
  { value: 'Asia/Jayapura', label: 'Asia/Jayapura (WIT, GMT+9)' },
  { value: 'Asia/Singapore', label: 'Asia/Singapore (GMT+8)' },
  { value: 'UTC', label: 'UTC (GMT+0)' },
  { value: 'Europe/London', label: 'Europe/London (GMT/BST)' },
  { value: 'Europe/Paris', label: 'Europe/Paris (CET/CEST)' },
  { value: 'America/New_York', label: 'America/New_York (EST/EDT)' },
  { value: 'America/Los_Angeles', label: 'America/Los_Angeles (PST/PDT)' },
  { value: 'Asia/Tokyo', label: 'Asia/Tokyo (JST, GMT+9)' },
  { value: 'Australia/Sydney', label: 'Australia/Sydney (AEST/AEDT)' },
];

const SELECT_CLASS = 'flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50';

export function AutomationTab({ site, updateSite, onChange }: SiteTabProps) {
  const isActive = site.is_active !== false;
  return (
    <TabPanel id="automation">
      <SettingToggleRow
        title="Status Website"
        description="Matikan untuk menonaktifkan bot sepenuhnya di website ini."
        checked={isActive}
        onToggle={() => updateSite({ is_active: !isActive })}
      />
      <SettingToggleRow
        title="Posting Otomatis"
        description="Buat dan terbitkan artikel secara otomatis sesuai jadwal."
        checked={site.auto_post || false}
        onToggle={() => updateSite({ auto_post: !site.auto_post })}
      />

      <div className="pt-4 border-t grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="space-y-2">
          <Label htmlFor="schedule_hours" className="text-foreground">Jadwal Posting (Jam)</Label>
          <Input id="schedule_hours" name="schedule_hours" value={site.schedule_hours || ''} onChange={onChange} placeholder="0, 6, 12, 18" className="bg-background" />
          <p className="text-[11px] text-muted-foreground leading-tight">Jam dipisahkan koma (0-23). Contoh: 0, 6, 12, 18</p>
        </div>
        <div className="space-y-2">
          <Label htmlFor="timezone" className="text-foreground">Zona Waktu</Label>
          <select
            id="timezone"
            name="timezone"
            value={site.timezone || 'Asia/Jakarta'}
            onChange={(e) => updateSite({ timezone: e.target.value })}
            className={SELECT_CLASS}
          >
            {TIMEZONES.map(tz => <option key={tz.value} value={tz.value}>{tz.label}</option>)}
          </select>
          <p className="text-[11px] text-muted-foreground leading-tight">Zona waktu untuk jadwal posting website ini.</p>
        </div>
        <div className="space-y-2">
          <Label htmlFor="language" className="text-foreground">Bahasa</Label>
          <select
            id="language"
            name="language"
            value={site.language || 'id'}
            onChange={(e) => updateSite({ language: e.target.value })}
            className={SELECT_CLASS}
          >
            <option value="id">Bahasa Indonesia</option>
            <option value="en">Bahasa Inggris (US/UK)</option>
          </select>
          <p className="text-[11px] text-muted-foreground leading-tight">Bahasa artikel yang dihasilkan.</p>
        </div>
      </div>
    </TabPanel>
  );
}
