import { useState } from 'react';
import { CreditCard } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useBilling } from '@/hooks/useBilling';
import { CreditBalanceCard } from '@/components/billing/CreditBalanceCard';
import { TopUpForm } from '@/components/billing/TopUpForm';
import { InvoiceDetails } from '@/components/billing/InvoiceDetails';
import { PaymentHistoryTable } from '@/components/billing/PaymentHistoryTable';

const PRICE_PER_CREDIT_IDR = 2000;

export default function Billing() {
  const billing = useBilling();
  const [creditsCount, setCreditsCount] = useState<number>(25);
  const [paymentCode, setPaymentCode] = useState<string>('QRIS2'); // Tripay default
  const { activeInvoice } = billing;
  const cost = creditsCount * PRICE_PER_CREDIT_IDR;

  if (billing.loading) return <div className="p-8">Memuat informasi tagihan...</div>;

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-primary to-indigo-600 dark:from-primary dark:to-indigo-400 bg-clip-text text-transparent flex items-center gap-2">
          <CreditCard className="h-8 w-8 text-primary" /> Tagihan & Kredit
        </h1>
        <p className="text-muted-foreground">Isi ulang kredit penulisan artikel, ubah tier, dan lihat riwayat invoice.</p>
      </div>

      <div className="grid gap-6 md:grid-cols-3">
        <CreditBalanceCard profile={billing.profile} />

        <Card className="border-border/50 shadow-md md:col-span-2">
          <CardHeader>
            <CardTitle>Top Up Kredit</CardTitle>
            <CardDescription>Pesan kredit tambahan secara instan.</CardDescription>
          </CardHeader>
          <CardContent>
            {!activeInvoice ? (
              <TopUpForm
                creditsCount={creditsCount}
                onCreditsCountChange={setCreditsCount}
                cost={cost}
                enabled={billing.enabled}
                paymentMethod={billing.paymentMethod}
                onPaymentMethodChange={billing.setPaymentMethod}
                paymentCode={paymentCode}
                onPaymentCodeChange={setPaymentCode}
                processing={billing.processing}
                onSubmit={() => billing.createInvoice(creditsCount, paymentCode)}
              />
            ) : (
              <InvoiceDetails
                invoice={activeInvoice}
                fallbackAmount={cost}
                processing={billing.processing}
                onCancel={() => billing.setActiveInvoice(null)}
                onUploadReceipt={(file) => billing.uploadReceipt(activeInvoice.invoice_id, file)}
                onSimulateTripayPaid={billing.simulateTripayPaid}
                onSimulatePayPal={billing.simulatePayPal}
              />
            )}
          </CardContent>
        </Card>
      </div>

      <PaymentHistoryTable
        history={billing.history}
        onViewInvoice={(tx) => {
          setCreditsCount(tx.credits_purchased);
          billing.setActiveInvoice({
            invoice_id: tx.invoice_id,
            payment_method: tx.payment_method,
            amount: tx.amount,
            bank_details: tx.bank_details,
          });
          window.scrollTo({ top: 0, behavior: 'smooth' });
        }}
      />
    </div>
  );
}
