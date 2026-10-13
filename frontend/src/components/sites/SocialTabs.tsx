import type { ReactNode } from 'react';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { SettingToggleRow } from './SettingToggleRow';
import { TabPanel } from './TabPanel';
import { SAVED_SECRET_PLACEHOLDER, type SiteTabProps } from './siteForm';

/** Fields shown below an integration switch once it is enabled. */
function EnabledFields({ enabled, children }: { enabled: boolean | undefined; children: ReactNode }) {
  if (!enabled) return null;
  return <div className="space-y-4 pt-4 border-t border-border/50">{children}</div>;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      {children}
    </div>
  );
}

export function TelegramTab({ site, updateSite, onChange }: SiteTabProps) {
  return (
    <TabPanel id="telegram">
      <SettingToggleRow
        title="Integrasi Telegram"
        description="Kirim artikel otomatis ke channel Telegram atau beri notifikasi ke chat admin."
        ariaLabel="Aktifkan integrasi Telegram"
        checked={site.telegram_enabled || false}
        onToggle={() => updateSite({ telegram_enabled: !site.telegram_enabled })}
      />
      <EnabledFields enabled={site.telegram_enabled}>
        <Field label="Bot Token">
          <Input name="telegram_bot_token" type="password" value={site.telegram_bot_token || ''} onChange={onChange} placeholder={site.has_telegram_bot_token ? SAVED_SECRET_PLACEHOLDER : 'Bot token'} />
        </Field>
        <Field label="Chat ID Admin (untuk notifikasi)">
          <Input name="telegram_chat_id" value={site.telegram_chat_id || ''} onChange={onChange} />
        </Field>
        <SettingToggleRow
          compact
          title="Kirim artikel ke Channel Telegram"
          description="Teruskan artikel yang baru terbit ke Channel Telegram secara otomatis."
          checked={site.telegram_post_to_channel || false}
          onToggle={() => updateSite({ telegram_post_to_channel: !site.telegram_post_to_channel })}
        />
        {site.telegram_post_to_channel && (
          <div className="space-y-2 pl-6">
            <Label>Channel ID (mis. @channelsaya)</Label>
            <Input name="telegram_channel_id" value={site.telegram_channel_id || ''} onChange={onChange} />
          </div>
        )}
      </EnabledFields>
    </TabPanel>
  );
}

export function FacebookTab({ site, updateSite, onChange }: SiteTabProps) {
  return (
    <TabPanel id="facebook">
      <SettingToggleRow
        title="Posting ke Halaman Facebook"
        description="Kirim artikel baru ke feed Halaman Facebook Anda secara otomatis."
        ariaLabel="Aktifkan integrasi Facebook"
        checked={site.facebook_enabled || false}
        onToggle={() => updateSite({ facebook_enabled: !site.facebook_enabled })}
      />
      <EnabledFields enabled={site.facebook_enabled}>
        <Field label="Page ID">
          <Input name="facebook_page_id" value={site.facebook_page_id || ''} onChange={onChange} />
        </Field>
        <Field label="Access Token">
          <Input name="facebook_access_token" type="password" value={site.facebook_access_token || ''} onChange={onChange} placeholder={site.has_facebook_access_token ? SAVED_SECRET_PLACEHOLDER : 'Access token'} />
        </Field>
      </EnabledFields>
    </TabPanel>
  );
}

export function PinterestTab({ site, updateSite, onChange }: SiteTabProps) {
  return (
    <TabPanel id="pinterest">
      <SettingToggleRow
        title="Auto-Pin Pinterest"
        description="Kirim artikel baru ke Board Pinterest Anda secara otomatis."
        ariaLabel="Aktifkan integrasi Pinterest"
        checked={site.pinterest_enabled || false}
        onToggle={() => updateSite({ pinterest_enabled: !site.pinterest_enabled })}
      />
      <EnabledFields enabled={site.pinterest_enabled}>
        <Field label="Board ID">
          <Input name="pinterest_board_id" value={site.pinterest_board_id || ''} onChange={onChange} />
        </Field>
        <Field label="Access Token (Bearer)">
          <Input name="pinterest_access_token" type="password" value={site.pinterest_access_token || ''} onChange={onChange} placeholder={site.has_pinterest_access_token ? SAVED_SECRET_PLACEHOLDER : 'Access token'} />
        </Field>
      </EnabledFields>
    </TabPanel>
  );
}

const TWITTER_FIELDS = [
  { name: 'twitter_api_key', label: 'API Key', savedFlag: 'has_twitter_api_key' },
  { name: 'twitter_api_secret', label: 'API Secret', savedFlag: 'has_twitter_api_secret' },
  { name: 'twitter_access_token', label: 'Access Token', savedFlag: 'has_twitter_access_token' },
  { name: 'twitter_access_secret', label: 'Access Secret', savedFlag: 'has_twitter_access_secret' },
] as const;

export function TwitterTab({ site, updateSite, onChange }: SiteTabProps) {
  return (
    <TabPanel id="twitter">
      <SettingToggleRow
        title="Posting ke Twitter (X)"
        description="Bagikan tautan artikel baru ke X/Twitter secara otomatis."
        ariaLabel="Aktifkan integrasi Twitter"
        checked={site.twitter_enabled || false}
        onToggle={() => updateSite({ twitter_enabled: !site.twitter_enabled })}
      />
      <EnabledFields enabled={site.twitter_enabled}>
        <div className="grid grid-cols-2 gap-4">
          {TWITTER_FIELDS.map(field => (
            <Field key={field.name} label={field.label}>
              <Input name={field.name} type="password" value={site[field.name] || ''} onChange={onChange} placeholder={site[field.savedFlag] ? 'Tersimpan' : field.label} />
            </Field>
          ))}
        </div>
      </EnabledFields>
    </TabPanel>
  );
}

export function ThreadsTab({ site, updateSite, onChange }: SiteTabProps) {
  return (
    <TabPanel id="threads">
      <SettingToggleRow
        title="Posting ke Threads"
        description="Bagikan tautan artikel baru ke Instagram Threads secara otomatis."
        ariaLabel="Aktifkan integrasi Threads"
        checked={site.threads_enabled || false}
        onToggle={() => updateSite({ threads_enabled: !site.threads_enabled })}
      />
      <EnabledFields enabled={site.threads_enabled}>
        <Field label="User ID">
          <Input name="threads_user_id" value={site.threads_user_id || ''} onChange={onChange} />
        </Field>
        <Field label="Access Token">
          <Input name="threads_access_token" type="password" value={site.threads_access_token || ''} onChange={onChange} placeholder={site.has_threads_access_token ? SAVED_SECRET_PLACEHOLDER : 'Access token'} />
        </Field>
      </EnabledFields>
    </TabPanel>
  );
}
