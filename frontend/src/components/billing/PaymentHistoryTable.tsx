import { Eye } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import type { BillingHistoryItem } from '@/lib/types';

const STATUS_LABELS: Record<string, string> = {
  success: 'Berhasil',
  awaiting_approval: 'Menunggu Admin',
  pending: 'Menunggu Pembayaran',
  failed: 'Gagal',
  rejected: 'Ditolak',
  expired: 'Kedaluwarsa',
  canceled: 'Dibatalkan',
  cancelled: 'Dibatalkan',
};

const STATUS_CLASSES: Record<string, string> = {
  success: 'bg-green-500/15 text-green-500',
  awaiting_approval: 'bg-indigo-500/15 text-indigo-500',
  pending: 'bg-yellow-500/15 text-yellow-500',
};

interface PaymentHistoryTableProps {
  history: BillingHistoryItem[];
  /** Reopens a pending manual-transfer invoice. */
  onViewInvoice: (tx: BillingHistoryItem) => void;
}

export function PaymentHistoryTable({ history, onViewInvoice }: PaymentHistoryTableProps) {
  return (
    <Card className="border-border/50 shadow-md">
      <CardHeader>
        <CardTitle>Riwayat Pembayaran</CardTitle>
        <CardDescription>Tinjau semua transaksi kredit dan unggahan bukti transfer Anda.</CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full text-sm text-left border-collapse">
          <thead>
            <tr className="border-b bg-muted/40 font-semibold text-muted-foreground">
              <th className="p-4">ID Invoice</th>
              <th className="p-4">Tanggal</th>
              <th className="p-4">Metode</th>
              <th className="p-4 text-right">Kredit</th>
              <th className="p-4 text-right">Total (IDR)</th>
              <th className="p-4">Status</th>
              <th className="p-4 text-center">Bukti</th>
            </tr>
          </thead>
          <tbody>
            {history.map((tx) => (
              <tr key={tx.id} className="border-b hover:bg-secondary/20 transition-colors">
                <td className="p-4 font-mono font-bold text-xs">{tx.invoice_id}</td>
                <td className="p-4 text-muted-foreground whitespace-nowrap">{tx.created_at}</td>
                <td className="p-4 font-medium capitalize">{tx.payment_method}</td>
                <td className="p-4 text-right font-bold text-primary">{tx.credits_purchased}</td>
                <td className="p-4 text-right font-medium">Rp {tx.amount?.toLocaleString('id-ID')}</td>
                <td className="p-4">
                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold ${STATUS_CLASSES[tx.status] ?? 'bg-red-500/15 text-red-500'}`}>
                    {STATUS_LABELS[tx.status] ?? tx.status}
                  </span>
                </td>
                <td className="p-4 text-center">
                  {tx.status === 'pending' && tx.payment_method === 'manual' ? (
                    <div className="flex justify-center">
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-8 text-xs bg-indigo-50 hover:bg-indigo-100 text-indigo-700 border-indigo-200"
                        onClick={() => onViewInvoice(tx)}
                      >
                        <Eye className="h-3 w-3 mr-1" /> Lihat Invoice
                      </Button>
                    </div>
                  ) : tx.receipt_url ? (
                    <a href={tx.receipt_url} target="_blank" rel="noreferrer" className="inline-flex items-center text-xs text-indigo-700 dark:text-indigo-400 hover:underline gap-1">
                      <Eye className="h-3 w-3" /> Lihat Bukti
                    </a>
                  ) : (
                    <span className="text-xs text-muted-foreground">-</span>
                  )}
                </td>
              </tr>
            ))}
            {history.length === 0 && (
              <tr>
                <td colSpan={7} className="p-8 text-center text-muted-foreground">
                  Belum ada transaksi.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
