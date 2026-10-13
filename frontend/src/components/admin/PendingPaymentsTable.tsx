import { Eye, Check, X } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import type { PendingPayment } from '@/lib/types';

interface PendingPaymentsTableProps {
  payments: PendingPayment[];
  onApprove: (id: number) => void;
  onReject: (id: number) => void;
}

export function PendingPaymentsTable({ payments, onApprove, onReject }: PendingPaymentsTableProps) {
  return (
    <Card className="border-border/50 shadow-md">
      <CardHeader>
        <CardTitle>Persetujuan Pembayaran Manual</CardTitle>
        <CardDescription>Verifikasi bukti transfer pengguna dan tambahkan kredit secara instan.</CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full text-sm text-left border-collapse">
          <thead>
            <tr className="border-b bg-muted/40 font-semibold text-muted-foreground">
              <th className="p-4">ID Invoice</th>
              <th className="p-4">Tanggal</th>
              <th className="p-4">Pengguna</th>
              <th className="p-4 text-right">Kredit Diminta</th>
              <th className="p-4 text-right">Jumlah (IDR)</th>
              <th className="p-4 text-center">Bukti</th>
              <th className="p-4 text-center">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {payments.map((tx) => (
              <tr key={tx.id} className="border-b hover:bg-secondary/20 transition-colors">
                <td className="p-4 font-mono font-bold text-xs">{tx.invoice_id}</td>
                <td className="p-4 text-muted-foreground whitespace-nowrap">{tx.created_at}</td>
                <td className="p-4">
                  <div className="flex flex-col">
                    <span className="font-semibold text-xs">{tx.user_name}</span>
                    <span className="text-[10px] text-muted-foreground">{tx.user_email}</span>
                  </div>
                </td>
                <td className="p-4 text-right font-black text-primary">{tx.credits_purchased}</td>
                <td className="p-4 text-right font-semibold">Rp {tx.amount?.toLocaleString('id-ID')}</td>
                <td className="p-4 text-center">
                  {tx.receipt_url ? (
                    <a href={tx.receipt_url} target="_blank" rel="noreferrer" className="inline-flex items-center text-xs text-indigo-400 hover:underline gap-1">
                      <Eye className="h-4 w-4" /> Lihat Bukti
                    </a>
                  ) : (
                    <span className="text-xs text-yellow-500 font-medium">Bukti belum diunggah</span>
                  )}
                </td>
                <td className="p-4 text-center">
                  <div className="flex items-center justify-center gap-2">
                    <Button
                      size="sm"
                      onClick={() => onApprove(tx.id)}
                      className="h-8 bg-green-600 hover:bg-green-500 gap-1 px-3 text-xs"
                      disabled={!tx.receipt_url}
                    >
                      <Check className="h-3.5 w-3.5" /> Setujui
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={() => onReject(tx.id)}
                      className="h-8 gap-1 px-3 text-xs"
                    >
                      <X className="h-3.5 w-3.5" /> Tolak
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
            {payments.length === 0 && (
              <tr>
                <td colSpan={7} className="p-8 text-center text-muted-foreground font-medium">
                  Tidak ada pembayaran yang menunggu persetujuan.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
