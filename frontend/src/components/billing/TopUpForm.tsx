import type { ReactNode } from 'react';
import { CreditCard, Wallet } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { PaymentMethod, PaymentMethodsEnabled } from '@/lib/types';

const MIN_CREDITS = 25;

interface TopUpFormProps {
  creditsCount: number;
  onCreditsCountChange: (count: number) => void;
  cost: number;
  enabled: PaymentMethodsEnabled;
  paymentMethod: PaymentMethod;
  onPaymentMethodChange: (method: PaymentMethod) => void;
  paymentCode: string;
  onPaymentCodeChange: (code: string) => void;
  processing: boolean;
  onSubmit: () => void;
}

interface MethodOptionProps {
  value: PaymentMethod;
  selected: PaymentMethod;
  onSelect: (method: PaymentMethod) => void;
  icon: ReactNode;
  title: string;
  subtitle: string;
}

function MethodOption({ value, selected, onSelect, icon, title, subtitle }: MethodOptionProps) {
  return (
    <label className={`flex items-center gap-3 p-4 rounded-xl border-2 cursor-pointer transition-all ${selected === value ? 'border-primary bg-primary/5' : 'border-border hover:bg-secondary/40'}`}>
      <input
        type="radio"
        name="payment_method"
        value={value}
        checked={selected === value}
        onChange={() => onSelect(value)}
        className="sr-only"
      />
      {icon}
      <div className="text-left">
        <p className="font-bold text-sm">{title}</p>
        <p className="text-xs text-muted-foreground">{subtitle}</p>
      </div>
    </label>
  );
}

export function TopUpForm(props: TopUpFormProps) {
  const { creditsCount, onCreditsCountChange, cost, enabled, paymentMethod, onPaymentMethodChange, paymentCode, onPaymentCodeChange, processing, onSubmit } = props;
  const noMethods = !enabled.manual && !enabled.tripay && !enabled.paypal;

  return (
    <form onSubmit={(e) => { e.preventDefault(); onSubmit(); }} className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="credits_count">Jumlah Kredit</Label>
          <Input
            id="credits_count"
            type="number"
            min={MIN_CREDITS}
            value={creditsCount}
            onChange={(e) => onCreditsCountChange(Math.max(MIN_CREDITS, parseInt(e.target.value) || 0))}
            required
          />
        </div>

        <div className="space-y-2">
          <Label>Total Biaya</Label>
          <div className="h-8 px-2.5 py-1 rounded-lg border border-input bg-muted/30 font-bold text-sm text-foreground flex items-center justify-between">
            <span>Rp {cost.toLocaleString('id-ID')}</span>
            <span className="text-xs text-muted-foreground font-normal">(USD ~{(cost / 16000).toFixed(2)})</span>
          </div>
        </div>
      </div>

      <div className="space-y-3">
        <Label>Metode Pembayaran</Label>
        {noMethods ? (
          <div className="p-4 rounded-xl bg-destructive/10 border border-destructive/20 text-destructive text-sm text-center">
            Metode pembayaran tidak tersedia saat ini. Silakan hubungi admin.
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-3">
            {enabled.manual && (
              <MethodOption value="manual" selected={paymentMethod} onSelect={onPaymentMethodChange}
                icon={<Wallet className="h-5 w-5 text-indigo-500" />} title="Transfer Manual" subtitle="Mandiri / VA, verifikasi admin" />
            )}
            {enabled.tripay && (
              <MethodOption value="tripay" selected={paymentMethod} onSelect={onPaymentMethodChange}
                icon={<CreditCard className="h-5 w-5 text-emerald-500" />} title="Tripay Gateway" subtitle="QRIS, VA, E-Wallet" />
            )}
            {enabled.paypal && (
              <MethodOption value="paypal" selected={paymentMethod} onSelect={onPaymentMethodChange}
                icon={<CreditCard className="h-5 w-5 text-blue-500" />} title="PayPal Checkout" subtitle="USD / Kartu Kredit" />
            )}
          </div>
        )}
      </div>

      {paymentMethod === 'tripay' && enabled.tripay && (
        <div className="space-y-2">
          <Label htmlFor="payment_code">Pilih Kanal Tripay</Label>
          <select
            id="payment_code"
            value={paymentCode}
            onChange={(e) => onPaymentCodeChange(e.target.value)}
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          >
            <option value="QRIS2">QRIS (Deteksi otomatis)</option>
            <option value="BRIVA">BRI Virtual Account</option>
            <option value="MANDIRIVA">Mandiri Virtual Account</option>
            <option value="BCAVA">BCA Virtual Account</option>
            <option value="ALFAMART">Alfamart</option>
          </select>
        </div>
      )}

      <Button type="submit" disabled={processing || noMethods} className="w-full bg-gradient-to-r from-primary to-indigo-600 hover:from-primary/95 hover:to-indigo-600/95 font-bold shadow-md py-6">
        {processing ? 'Memproses Pesanan...' : 'Buat Invoice'}
      </Button>
    </form>
  );
}
