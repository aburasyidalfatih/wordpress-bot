import { useState } from 'react';
import type { ReactNode } from 'react';
import { CreditCard, Upload, MessageSquare } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { BankDetails, InvoiceData } from '@/lib/types';

const SANDBOX_NOTE = 'Karena ini mode sandbox/pengujian lokal,';

function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return <div className="flex justify-between"><span>{label}</span> {children}</div>;
}

function whatsappLink(bank: BankDetails, invoiceId: string, amount: number) {
  const phone = (bank.whatsapp_number || '').replace(/[^0-9]/g, '');
  const text = `Halo Admin, saya ingin konfirmasi pembayaran manual untuk Invoice ${invoiceId} sebesar Rp ${amount.toLocaleString('id-ID')}`;
  return `https://wa.me/${phone}?text=${encodeURIComponent(text)}`;
}

interface ManualTransferPanelProps {
  invoice: InvoiceData;
  bank: BankDetails;
  amount: number;
  processing: boolean;
  onUploadReceipt: (file: File | null) => void;
}

function ManualTransferPanel({ invoice, bank, amount, processing, onUploadReceipt }: ManualTransferPanelProps) {
  const [receiptFile, setReceiptFile] = useState<File | null>(null);
  return (
    <div className="space-y-4">
      <div className="p-4 rounded-xl border border-indigo-500/20 bg-indigo-500/5 space-y-3">
        <h4 className="font-bold text-indigo-700 dark:text-indigo-400">Instruksi Transfer Manual</h4>
        <p className="text-sm">Silakan transfer tepat <b>Rp {amount.toLocaleString('id-ID')}</b> ke rekening berikut:</p>
        <div className="grid gap-2 text-sm font-medium mt-2 bg-background/50 p-3 rounded-lg">
          <DetailRow label="Bank:"><span>{bank.bank_name}</span></DetailRow>
          <DetailRow label="Nomor Rekening:"><span className="font-black text-indigo-300">{bank.account_number}</span></DetailRow>
          <DetailRow label="Atas Nama:"><span>{bank.account_holder}</span></DetailRow>
        </div>
        {bank.whatsapp_number && (
          <div className="pt-2">
            <a
              href={whatsappLink(bank, invoice.invoice_id, amount)}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center justify-center gap-2 w-full px-4 py-2.5 text-sm font-bold text-white bg-green-600 hover:bg-green-700 rounded-xl shadow-md transition-all"
            >
              <MessageSquare className="h-4 w-4" /> Konfirmasi via WhatsApp
            </a>
          </div>
        )}
      </div>

      <form onSubmit={(e) => { e.preventDefault(); onUploadReceipt(receiptFile); }} className="space-y-3">
        <Label htmlFor="receipt">Unggah Bukti Pembayaran</Label>
        <div className="flex items-center gap-2">
          <Input
            id="receipt"
            type="file"
            accept="image/jpeg,image/png,image/webp,application/pdf"
            onChange={(e) => setReceiptFile(e.target.files?.[0] || null)}
            required
          />
          <Button type="submit" disabled={processing} className="bg-indigo-600">
            <Upload className="h-4 w-4 mr-1" /> Kirim
          </Button>
        </div>
      </form>
    </div>
  );
}

function TripayPanel({ invoice, processing, onSimulatePaid }: { invoice: InvoiceData; processing: boolean; onSimulatePaid: () => void }) {
  const tripay = invoice.tripay_data!;
  return (
    <div className="space-y-4">
      <div className="p-4 rounded-xl border border-emerald-500/20 bg-emerald-500/5 space-y-2">
        <h4 className="font-bold text-emerald-700 dark:text-emerald-400">Detail Pembayaran Tripay</h4>
        <p className="text-sm">Invoice dibuat untuk {tripay.payment_name}.</p>
        <div className="grid gap-2 text-sm font-medium mt-2 bg-background/50 p-3 rounded-lg">
          <DetailRow label="Metode Pembayaran:"><span>{tripay.payment_name}</span></DetailRow>
          <DetailRow label="Jumlah:"><span>Rp {tripay.amount?.toLocaleString('id-ID')}</span></DetailRow>
          {tripay.pay_code && (
            <DetailRow label="Kode Bayar / VA:"><span className="font-black text-emerald-300">{tripay.pay_code}</span></DetailRow>
          )}
          <DetailRow label="Kode Referensi:"><span>{tripay.reference}</span></DetailRow>
        </div>

        {invoice.checkout_url && (
          <div className="pt-4">
            <a
              href={invoice.checkout_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center justify-center gap-2 w-full px-4 py-2.5 text-sm font-bold text-white bg-emerald-600 hover:bg-emerald-500 rounded-xl shadow-md transition-all"
            >
              <CreditCard className="h-4 w-4" /> Buka Halaman Pembayaran Tripay
            </a>
            <p className="text-xs text-muted-foreground mt-2">Kredit ditambahkan otomatis setelah Tripay mengonfirmasi pembayaran. Muat ulang halaman ini setelah membayar.</p>
          </div>
        )}

        {invoice.is_mock && (
          <div className="flex flex-col gap-2 pt-4">
            <p className="text-xs text-muted-foreground">{SANDBOX_NOTE} Anda dapat langsung menyimulasikan webhook PAID di bawah ini:</p>
            <Button type="button" onClick={onSimulatePaid} disabled={processing} className="w-full bg-emerald-600 hover:bg-emerald-500">
              Simulasikan Callback Tripay (PAID)
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

function PayPalPanel({ invoice, processing, onSimulateCapture }: { invoice: InvoiceData; processing: boolean; onSimulateCapture: () => void }) {
  const approveUrl = invoice.paypal_approve_url;
  return (
    <div className="space-y-4">
      <div className="p-4 rounded-xl border border-blue-500/20 bg-blue-500/5 space-y-2">
        <h4 className="font-bold text-blue-700 dark:text-blue-400">Detail Pembayaran PayPal</h4>
        <p className="text-sm">ID Order PayPal: <b>{invoice.paypal_order_id}</b></p>
        <p className="text-sm">Total pembayaran: <b>${invoice.amount_usd} USD</b></p>

        {invoice.is_mock ? (
          <div className="flex flex-col gap-2 pt-4">
            <p className="text-xs text-muted-foreground">{SANDBOX_NOTE} Anda dapat menyimulasikan capture order PayPal yang berhasil di bawah ini:</p>
            <Button type="button" onClick={onSimulateCapture} disabled={processing} className="w-full bg-blue-600 hover:bg-blue-500">
              Simulasikan Capture PayPal & Selesaikan
            </Button>
          </div>
        ) : approveUrl ? (
          <div className="flex flex-col gap-2 pt-4">
            <Button
              type="button"
              onClick={() => { window.location.href = approveUrl; }}
              disabled={processing}
              className="w-full bg-blue-600 hover:bg-blue-500"
            >
              Bayar dengan PayPal
            </Button>
            <p className="text-xs text-muted-foreground">Anda akan diarahkan ke PayPal lalu kembali ke halaman ini untuk menyelesaikan pembayaran.</p>
          </div>
        ) : (
          <p className="text-xs text-destructive pt-4">PayPal tidak mengembalikan tautan pembayaran. Silakan buat invoice baru.</p>
        )}
      </div>
    </div>
  );
}

interface InvoiceDetailsProps {
  invoice: InvoiceData;
  /** Shown when the invoice itself has no amount (e.g. reopened from history). */
  fallbackAmount: number;
  processing: boolean;
  onCancel: () => void;
  onUploadReceipt: (file: File | null) => void;
  onSimulateTripayPaid: () => void;
  onSimulatePayPal: () => void;
}

export function InvoiceDetails({ invoice, fallbackAmount, processing, onCancel, onUploadReceipt, onSimulateTripayPaid, onSimulatePayPal }: InvoiceDetailsProps) {
  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center p-4 rounded-xl bg-secondary/30 border">
        <div>
          <span className="text-xs text-muted-foreground">Nomor Invoice</span>
          <h4 className="text-lg font-black text-foreground">{invoice.invoice_id}</h4>
        </div>
        <Button variant="ghost" size="sm" onClick={onCancel} className="text-muted-foreground">
          Batalkan Invoice
        </Button>
      </div>

      {invoice.payment_method === 'manual' && invoice.bank_details && (
        <ManualTransferPanel
          invoice={invoice}
          bank={invoice.bank_details}
          amount={invoice.amount || fallbackAmount}
          processing={processing}
          onUploadReceipt={onUploadReceipt}
        />
      )}

      {invoice.payment_method === 'tripay' && invoice.tripay_data && (
        <TripayPanel invoice={invoice} processing={processing} onSimulatePaid={onSimulateTripayPaid} />
      )}

      {invoice.payment_method === 'paypal' && (
        <PayPalPanel invoice={invoice} processing={processing} onSimulateCapture={onSimulatePayPal} />
      )}
    </div>
  );
}
