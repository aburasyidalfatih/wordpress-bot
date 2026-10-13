import { DollarSign } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ToggleSwitch } from '@/components/ToggleSwitch';
import type { AdminConfig } from '@/lib/types';
import { ConfigInput, type ConfigFormProps } from './ConfigInput';

type GatewayFlag = 'PAYMENT_TRIPAY_ENABLED' | 'PAYMENT_PAYPAL_ENABLED' | 'PAYMENT_MANUAL_ENABLED';

function GatewayHeader({ title, flag, config, setConfig }: ConfigFormProps & { title: string; flag: GatewayFlag }) {
  // Gateways are enabled unless explicitly switched off.
  const enabled = config[flag] !== false;
  return (
    <>
      <div className="h-px bg-border my-2" />
      <div className="flex items-center justify-between">
        <h4 className="font-semibold text-sm text-foreground/85">{title}</h4>
        <ToggleSwitch
          size="sm"
          checked={enabled}
          onToggle={() => setConfig({ ...config, [flag]: !enabled } as AdminConfig)}
          ariaLabel={`Aktifkan ${title}`}
        />
      </div>
    </>
  );
}

export function PaymentSettingsCard(props: ConfigFormProps) {
  const { config, setConfig } = props;
  return (
    <Card className="border-border/50 shadow-md">
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          <DollarSign className="h-5 w-5 text-indigo-500" /> Pengaturan Pembayaran
        </CardTitle>
        <CardDescription>Atur kredensial Tripay dan PayPal untuk pembelian top-up kredit.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="PAYMENT_USD_RATE">Kurs konversi USD (IDR)</Label>
          <Input
            id="PAYMENT_USD_RATE"
            type="number"
            min="0.01"
            step="any"
            value={config.PAYMENT_USD_RATE || 16000}
            onChange={(e) => setConfig({ ...config, PAYMENT_USD_RATE: parseFloat(e.target.value) || 0 })}
            placeholder="mis. 16000"
            required
          />
        </div>

        <GatewayHeader {...props} title="Tripay (Gateway IDR)" flag="PAYMENT_TRIPAY_ENABLED" />
        <div className="grid gap-4 sm:grid-cols-2">
          <ConfigInput {...props} field="TRIPAY_MERCHANT_CODE" label="Kode Merchant" placeholder="T12345" />
          <ConfigInput {...props} field="TRIPAY_API_URL" label="API URL" placeholder="https://tripay.co.id/api-sandbox" />
        </div>
        <ConfigInput {...props} field="TRIPAY_API_KEY" label="API Key" type="password" savedFlag="has_TRIPAY_API_KEY" placeholder="API Key Tripay Anda" />
        <ConfigInput {...props} field="TRIPAY_PRIVATE_KEY" label="Private Key" type="password" savedFlag="has_TRIPAY_PRIVATE_KEY" placeholder="Private Key Tripay Anda" />

        <GatewayHeader {...props} title="PayPal (Gateway USD)" flag="PAYMENT_PAYPAL_ENABLED" />
        <div className="grid gap-4 sm:grid-cols-2">
          <ConfigInput {...props} field="PAYPAL_API_URL" label="API URL" placeholder="https://api-m.sandbox.paypal.com" />
          <ConfigInput {...props} field="PAYPAL_CLIENT_ID" label="Client ID" placeholder="Client ID PayPal" />
        </div>
        <ConfigInput {...props} field="PAYPAL_SECRET" label="Secret" type="password" savedFlag="has_PAYPAL_SECRET" placeholder="Secret Key PayPal" />

        <GatewayHeader {...props} title="Rekening Bank Manual (Gateway Lokal)" flag="PAYMENT_MANUAL_ENABLED" />
        <div className="grid gap-4 sm:grid-cols-2">
          <ConfigInput {...props} field="MANUAL_BANK_NAME" label="Nama Bank" placeholder="mis. Bank Mandiri" />
          <ConfigInput {...props} field="MANUAL_BANK_HOLDER" label="Nama Pemilik Rekening" placeholder="mis. ADMIN AUTOWP" />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <ConfigInput {...props} field="MANUAL_BANK_ACCOUNT" label="Nomor Rekening" placeholder="mis. 123-456-789" />
          <ConfigInput {...props} field="ADMIN_WHATSAPP" label="WhatsApp Konfirmasi" placeholder="mis. 628123456789" />
        </div>
      </CardContent>
    </Card>
  );
}
