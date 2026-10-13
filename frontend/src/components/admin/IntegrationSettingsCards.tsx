import type { ReactNode } from 'react';
import { Shield, Users } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ConfigInput, type ConfigFormProps } from './ConfigInput';

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
