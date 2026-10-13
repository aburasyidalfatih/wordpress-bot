import { CheckCircle2 } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import type { BillingProfile } from '@/lib/types';

const PERKS = [
  'Kredit tidak memiliki masa kedaluwarsa',
  '1 kredit = 1 artikel lengkap',
  'Otomatis naik ke tier Pro setelah pembelian',
];

export function CreditBalanceCard({ profile }: { profile: BillingProfile }) {
  return (
    <Card className="border-border/50 shadow-md md:col-span-1">
      <CardHeader className="pb-4">
        <CardTitle className="text-lg">Saldo Kredit</CardTitle>
        <CardDescription>Status kuota kredit Anda saat ini.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-baseline justify-between p-4 rounded-xl bg-gradient-to-br from-indigo-500/10 to-primary/10 border border-primary/20">
          <div>
            <p className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">Sisa</p>
            <h3 className="text-4xl font-black mt-1 text-primary">{profile.credits ?? 0}</h3>
          </div>
          <span className="text-xs bg-indigo-500/20 text-indigo-300 font-extrabold px-3 py-1 rounded-full capitalize">{profile.tier || 'free'}</span>
        </div>

        <div className="space-y-2 text-sm text-muted-foreground">
          {PERKS.map(perk => (
            <div key={perk} className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-green-500" />
              <span>{perk}</span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
