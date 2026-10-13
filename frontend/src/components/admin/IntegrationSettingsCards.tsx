import type { ReactNode } from 'react';
import { Shield, Users } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ConfigInput, type ConfigFormProps } from './ConfigInput';

const SELECT_CLASS = 'flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50';

const TEXT_MODELS = [
  { value: 'gemini-3.6-flash', label: 'Gemini 3.6 Flash (Terbaru!)' },
  { value: 'gemini-3.6-pro', label: 'Gemini 3.6 Pro (Baru!)' },
  { value: 'gemini-3.5-flash', label: 'Gemini 3.5 Flash (Stabil / Direkomendasikan)' },
  { value: 'gemini-3.1-flash-lite', label: 'Gemini 3.1 Flash-Lite (Stabil)' },
  { value: 'gemini-3.1-pro-preview', label: 'Gemini 3.1 Pro (Preview)' },
  { value: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro (Lama, Stabil)' },
  { value: 'gemini-1.5-flash', label: 'Gemini 1.5 Flash (Lama)' },
];

const IMAGE_MODELS = [
  { value: 'gemini-3.1-flash-image', label: 'Gemini 3.1 Flash Image (Stabil / Direkomendasikan)' },
  { value: 'gemini-3-pro-image', label: 'Gemini 3 Pro Image (Stabil / Kualitas Tinggi)' },
  { value: 'gemini-3.1-flash-lite-image', label: 'Gemini 3.1 Flash Lite Image (Stabil / Cepat)' },
  { value: 'gemini-3.1-flash-image-preview', label: 'Gemini 3.1 Flash Image (Preview)' },
];

function SettingsCard({ icon, title, description, children }: { icon: ReactNode; title: string; description: string; children: ReactNode }) {
  return (
    <Card className="border-border/50 shadow-md">
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          {icon} {title}
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">{children}</CardContent>
    </Card>
  );
}

export function GeminiSettingsCard(props: ConfigFormProps) {
  const { config, setConfig } = props;
  return (
    <SettingsCard
      icon={<Shield className="h-5 w-5 text-indigo-500" />}
      title="Konfigurasi Gemini AI"
      description="Atur API Google Gemini yang dipakai bersama untuk pembuatan konten."
    >
      <ConfigInput {...props} field="gemini_api_key" label="API Key" type="password" savedFlag="has_gemini_api_key" placeholder="API Key Gemini Anda" />
      <div className="space-y-2">
        <Label htmlFor="gemini_model">Model Teks</Label>
        <select
          id="gemini_model"
          value={config.gemini_model || 'gemini-3.5-flash'}
          onChange={(e) => setConfig({ ...config, gemini_model: e.target.value })}
          className={SELECT_CLASS}
        >
          {TEXT_MODELS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
        </select>
      </div>
      <div className="space-y-2">
        <Label htmlFor="gemini_image_model">Model Gambar</Label>
        <select
          id="gemini_image_model"
          value={config.gemini_image_model || 'gemini-3.1-flash-image'}
          onChange={(e) => setConfig({ ...config, gemini_image_model: e.target.value })}
          className={SELECT_CLASS}
        >
          {IMAGE_MODELS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
        </select>
      </div>
    </SettingsCard>
  );
}

export function GoogleOAuthSettingsCard(props: ConfigFormProps) {
  return (
    <SettingsCard
      icon={<Shield className="h-5 w-5 text-indigo-500" />}
      title="Google OAuth"
      description="Atur Client ID dan Client Secret Google untuk mengaktifkan Login Google."
    >
      <ConfigInput {...props} field="GOOGLE_CLIENT_ID" label="Google Client ID" placeholder="Client ID Google Anda" />
      <ConfigInput {...props} field="GOOGLE_CLIENT_SECRET" label="Google Client Secret" type="password" savedFlag="has_GOOGLE_CLIENT_SECRET" placeholder="Client Secret Google Anda" />
    </SettingsCard>
  );
}

export function NotificationSettingsCard(props: ConfigFormProps) {
  const { config, setConfig } = props;
  return (
    <SettingsCard
      icon={<Users className="h-5 w-5 text-indigo-500" />}
      title="Pengaturan Notifikasi"
      description="Atur SMTP Mailketing dan gateway WhatsApp Starsender."
    >
      <h4 className="font-semibold text-sm text-foreground/85">SMTP Mailketing</h4>
      <div className="grid gap-4 sm:grid-cols-3">
        <ConfigInput {...props} field="SMTP_HOST" label="SMTP Host" placeholder="smtp.mailketing.co.id" className="space-y-2 sm:col-span-2" />
        <div className="space-y-2">
          <Label htmlFor="SMTP_PORT">SMTP Port</Label>
          <Input
            id="SMTP_PORT"
            type="number"
            value={config.SMTP_PORT || 587}
            onChange={(e) => setConfig({ ...config, SMTP_PORT: parseInt(e.target.value) || 0 })}
            placeholder="587"
          />
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <ConfigInput {...props} field="SMTP_USER" label="SMTP User" placeholder="Username SMTP Anda" />
        <ConfigInput {...props} field="SMTP_PASSWORD" label="SMTP Password" type="password" savedFlag="has_SMTP_PASSWORD" placeholder="Password SMTP Anda" />
      </div>
      <ConfigInput {...props} field="SMTP_SENDER_EMAIL" label="Email Pengirim" type="email" placeholder="pengirim@domainanda.com" />

      <div className="h-px bg-border my-2" />
      <h4 className="font-semibold text-sm text-foreground/85">Gateway WA Starsender</h4>
      <div className="grid gap-4 sm:grid-cols-2">
        <ConfigInput {...props} field="STARSENDER_API_KEY" label="Starsender API Key" type="password" savedFlag="has_STARSENDER_API_KEY" placeholder="Starsender API Key" />
        <ConfigInput {...props} field="STARSENDER_DEVICE_ID" label="Device ID (Nomor HP)" placeholder="mis. 08123456789" />
      </div>
    </SettingsCard>
  );
}
