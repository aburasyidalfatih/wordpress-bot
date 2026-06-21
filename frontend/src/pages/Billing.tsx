import { useState, useEffect } from 'react';
import { CreditCard, Wallet, CheckCircle2, Upload, Eye, MessageSquare } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { toast } from 'sonner';
import { apiFetch } from '../lib/api';

interface InvoiceData {
  invoice_id: string;
  payment_method: string;
  amount?: number;
  amount_usd?: number;
  tripay_data?: {
    reference?: string;
    pay_code?: string;
    qr_string?: string;
    payment_name?: string;
    amount?: number;
    status?: string;
  };
  paypal_order_id?: string;
  bank_details?: {
    bank_name: string;
    account_number: string;
    account_holder: string;
    whatsapp_number?: string;
  };
}

export default function Billing() {
  const [profile, setProfile] = useState<any>({});
  const [creditsCount, setCreditsCount] = useState<number>(10);
  const [paymentMethod, setPaymentMethod] = useState<string>('manual');
  const [paymentCode, setPaymentCode] = useState<string>('QRIS2'); // Tripay default
  const [history, setHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [processing, setProcessing] = useState<boolean>(false);
  const [activeInvoice, setActiveInvoice] = useState<InvoiceData | null>(null);
  const [receiptFile, setReceiptFile] = useState<File | null>(null);
  const [tripayEnabled, setTripayEnabled] = useState<boolean>(true);
  const [paypalEnabled, setPaypalEnabled] = useState<boolean>(true);
  const [manualEnabled, setManualEnabled] = useState<boolean>(true);

  const fetchBillingInfo = async () => {
    try {
      const [profileRes, historyRes, configRes] = await Promise.all([
        apiFetch('/api/profile'),
        apiFetch('/api/payments/history'),
        apiFetch('/api/auth/config')
      ]);
      
      const profileData = await profileRes.json();
      const historyData = await historyRes.json();
      const configData = await configRes.json();

      if (profileData.success) {
        setProfile(profileData.profile);
      }
      if (historyData.success) {
        setHistory(historyData.history);
      }
      if (configData.success) {
        const isTripay = configData.payment_tripay_enabled !== false;
        const isPaypal = configData.payment_paypal_enabled !== false;
        const isManual = configData.payment_manual_enabled !== false;
        
        setTripayEnabled(isTripay);
        setPaypalEnabled(isPaypal);
        setManualEnabled(isManual);
        
        let defaultMethod = 'manual';
        if (!isManual) {
          if (isTripay) {
            defaultMethod = 'tripay';
          } else if (isPaypal) {
            defaultMethod = 'paypal';
          } else {
            defaultMethod = '';
          }
        }
        setPaymentMethod(defaultMethod);
      }
    } catch (e) {
      console.error(e);
      toast.error('Failed to load billing history');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchBillingInfo();
  }, []);

  const handleCreateInvoice = async (e: React.FormEvent) => {
    e.preventDefault();
    if (creditsCount <= 0) {
      toast.error('Credits count must be greater than 0');
      return;
    }
    setProcessing(true);
    try {
      const res = await apiFetch('/api/payments/create-invoice', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          credits_count: creditsCount,
          payment_method: paymentMethod,
          payment_code: paymentMethod === 'tripay' ? paymentCode : undefined
        })
      });
      const data = await res.json();
      if (data.success) {
        setActiveInvoice(data);
        toast.success('Invoice created successfully!');
        if (paymentMethod !== 'tripay' && paymentMethod !== 'paypal') {
          // Keep manual active view
        }
      } else {
        toast.error(data.error || 'Failed to create invoice');
      }
    } catch (err) {
      toast.error('Network error creating invoice');
    } finally {
      setProcessing(false);
    }
  };

  // Simulate PayPal Checkout
  const handleSimulatePayPal = async () => {
    if (!activeInvoice || !activeInvoice.paypal_order_id) return;
    setProcessing(true);
    try {
      const res = await apiFetch('/api/payments/paypal-capture', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          order_id: activeInvoice.paypal_order_id,
          invoice_id: activeInvoice.invoice_id
        })
      });
      const data = await res.json();
      if (data.success) {
        toast.success('Payment captured successfully! Credits added.');
        setActiveInvoice(null);
        fetchBillingInfo();
      } else {
        toast.error(data.error || 'Capture failed');
      }
    } catch (e) {
      toast.error('Error capturing payment');
    } finally {
      setProcessing(false);
    }
  };

  // Simulate Tripay Paid Webhook (locally)
  const handleSimulateTripayPaid = async () => {
    if (!activeInvoice || !activeInvoice.tripay_data) return;
    setProcessing(true);
    try {
      const res = await apiFetch('/api/payments/webhook/tripay', {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'X-Callback-Signature': 'mock_signature'
        },
        body: JSON.stringify({
          merchant_ref: activeInvoice.invoice_id,
          status: 'PAID',
          reference: activeInvoice.tripay_data.reference
        })
      });
      const data = await res.json();
      if (data.success) {
        toast.success('Tripay callback simulated! Credits added.');
        setActiveInvoice(null);
        fetchBillingInfo();
      } else {
        toast.error(data.message || 'Webhook failed');
      }
    } catch (e) {
      toast.error('Error simulating Tripay callback');
    } finally {
      setProcessing(false);
    }
  };

  // Manual Transfer Receipt Upload
  const handleUploadReceipt = async (e: React.FormEvent, customInvoiceId?: string) => {
    e.preventDefault();
    const targetInvoiceId = customInvoiceId || activeInvoice?.invoice_id;
    if (!targetInvoiceId) return;
    if (!receiptFile) {
      toast.error('Please select a receipt image first');
      return;
    }

    setProcessing(true);
    const formData = new FormData();
    formData.append('invoice_id', targetInvoiceId);
    formData.append('receipt', receiptFile);

    try {
      const res = await apiFetch('/api/payments/upload-receipt', {
        method: 'POST',
        body: formData
      });
      const data = await res.json();
      if (data.success) {
        toast.success(data.message || 'Receipt uploaded successfully!');
        setActiveInvoice(null);
        setReceiptFile(null);
        fetchBillingInfo();
      } else {
        toast.error(data.error || 'Failed to upload receipt');
      }
    } catch (err) {
      toast.error('Network error uploading receipt');
    } finally {
      setProcessing(false);
    }
  };

  const cost = creditsCount * 2000;

  if (loading) return <div className="p-8">Loading billing information...</div>;

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-primary to-indigo-600 dark:from-primary dark:to-indigo-400 bg-clip-text text-transparent flex items-center gap-2">
          <CreditCard className="h-8 w-8 text-primary" /> Billing & Credits
        </h1>
        <p className="text-muted-foreground">Top up your article writing credits, change tiers, and view invoice history.</p>
      </div>

      <div className="grid gap-6 md:grid-cols-3">
        {/* Credits Status Card */}
        <Card className="border-border/50 shadow-md md:col-span-1">
          <CardHeader className="pb-4">
            <CardTitle className="text-lg">Credit Balance</CardTitle>
            <CardDescription>Your current credit quota status.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-baseline justify-between p-4 rounded-xl bg-gradient-to-br from-indigo-500/10 to-primary/10 border border-primary/20">
              <div>
                <p className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">Remaining</p>
                <h3 className="text-4xl font-black mt-1 text-primary">{profile.credits !== undefined ? profile.credits : 0}</h3>
              </div>
              <span className="text-xs bg-indigo-500/20 text-indigo-300 font-extrabold px-3 py-1 rounded-full capitalize">{profile.tier || 'free'}</span>
            </div>
            
            <div className="space-y-2 text-sm text-muted-foreground">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-green-500" />
                <span>Credits do not expire</span>
              </div>
              <div className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-green-500" />
                <span>1 credit = 1 full article post</span>
              </div>
              <div className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-green-500" />
                <span>Auto-renews to Pro tier upon purchase</span>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Top-up Form Card */}
        <Card className="border-border/50 shadow-md md:col-span-2">
          <CardHeader>
            <CardTitle>Top Up Credits</CardTitle>
            <CardDescription>Order additional credits instantly.</CardDescription>
          </CardHeader>
          <CardContent>
            {!activeInvoice ? (
              <form onSubmit={handleCreateInvoice} className="space-y-6">
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="credits_count">Credits to Purchase</Label>
                    <Input
                      id="credits_count"
                      type="number"
                      min="1"
                      value={creditsCount}
                      onChange={(e) => setCreditsCount(Math.max(1, parseInt(e.target.value) || 0))}
                      required
                    />
                  </div>

                  <div className="space-y-2">
                    <Label>Calculated Cost</Label>
                    <div className="h-8 px-2.5 py-1 rounded-lg border border-input bg-muted/30 font-bold text-sm text-foreground flex items-center justify-between">
                      <span>Rp {cost.toLocaleString('id-ID')}</span>
                      <span className="text-xs text-muted-foreground font-normal">(USD ~{(cost/16000).toFixed(2)})</span>
                    </div>
                  </div>
                </div>

                <div className="space-y-3">
                  <Label>Payment Method</Label>
                  {!manualEnabled && !tripayEnabled && !paypalEnabled ? (
                    <div className="p-4 rounded-xl bg-destructive/10 border border-destructive/20 text-destructive text-sm text-center">
                      Metode pembayaran tidak tersedia saat ini. Silakan hubungi admin.
                    </div>
                  ) : (
                    <div className="grid gap-3 sm:grid-cols-3">
                      {manualEnabled && (
                        <label className={`flex items-center gap-3 p-4 rounded-xl border-2 cursor-pointer transition-all ${paymentMethod === 'manual' ? 'border-primary bg-primary/5' : 'border-border hover:bg-secondary/40'}`}>
                          <input 
                            type="radio" 
                            name="payment_method" 
                            value="manual"
                            checked={paymentMethod === 'manual'}
                            onChange={() => setPaymentMethod('manual')}
                            className="sr-only"
                          />
                          <Wallet className="h-5 w-5 text-indigo-500" />
                          <div className="text-left">
                            <p className="font-bold text-sm">Manual Transfer</p>
                            <p className="text-xs text-muted-foreground">Mandiri / VA approval</p>
                          </div>
                        </label>
                      )}

                      {tripayEnabled && (
                        <label className={`flex items-center gap-3 p-4 rounded-xl border-2 cursor-pointer transition-all ${paymentMethod === 'tripay' ? 'border-primary bg-primary/5' : 'border-border hover:bg-secondary/40'}`}>
                          <input 
                            type="radio" 
                            name="payment_method" 
                            value="tripay"
                            checked={paymentMethod === 'tripay'}
                            onChange={() => setPaymentMethod('tripay')}
                            className="sr-only"
                          />
                          <CreditCard className="h-5 w-5 text-emerald-500" />
                          <div className="text-left">
                            <p className="font-bold text-sm">Tripay Gateway</p>
                            <p className="text-xs text-muted-foreground">QRIS, VA, E-Wallet</p>
                          </div>
                        </label>
                      )}

                      {paypalEnabled && (
                        <label className={`flex items-center gap-3 p-4 rounded-xl border-2 cursor-pointer transition-all ${paymentMethod === 'paypal' ? 'border-primary bg-primary/5' : 'border-border hover:bg-secondary/40'}`}>
                          <input 
                            type="radio" 
                            name="payment_method" 
                            value="paypal"
                            checked={paymentMethod === 'paypal'}
                            onChange={() => setPaymentMethod('paypal')}
                            className="sr-only"
                          />
                          <CreditCard className="h-5 w-5 text-blue-500" />
                          <div className="text-left">
                            <p className="font-bold text-sm">PayPal Checkout</p>
                            <p className="text-xs text-muted-foreground">USD / Credit Card</p>
                          </div>
                        </label>
                      )}
                    </div>
                  )}
                </div>

                {paymentMethod === 'tripay' && tripayEnabled && (
                  <div className="space-y-2">
                    <Label htmlFor="payment_code">Select Tripay Code</Label>
                    <select
                      id="payment_code"
                      value={paymentCode}
                      onChange={(e) => setPaymentCode(e.target.value)}
                      className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    >
                      <option value="QRIS2">QRIS (Auto detect)</option>
                      <option value="BRIVA">BRI Virtual Account</option>
                      <option value="MANDIRIVA">Mandiri Virtual Account</option>
                      <option value="BCAVA">BCA Virtual Account</option>
                      <option value="ALFAMART">Alfamart</option>
                    </select>
                  </div>
                )}

                <Button type="submit" disabled={processing || (!manualEnabled && !tripayEnabled && !paypalEnabled)} className="w-full bg-gradient-to-r from-primary to-indigo-600 hover:from-primary/95 hover:to-indigo-600/95 font-bold shadow-md py-6">
                  {processing ? 'Processing Order...' : 'Generate Invoice'}
                </Button>
              </form>
            ) : (
              <div className="space-y-6">
                <div className="flex justify-between items-center p-4 rounded-xl bg-secondary/30 border">
                  <div>
                    <span className="text-xs text-muted-foreground">Invoice Reference</span>
                    <h4 className="text-lg font-black text-foreground">{activeInvoice.invoice_id}</h4>
                  </div>
                  <Button variant="ghost" size="sm" onClick={() => setActiveInvoice(null)} className="text-muted-foreground">
                    Cancel Invoice
                  </Button>
                </div>

                {activeInvoice.payment_method === 'manual' && activeInvoice.bank_details && (
                  <div className="space-y-4">
                    <div className="p-4 rounded-xl border border-indigo-500/20 bg-indigo-500/5 space-y-3">
                      <h4 className="font-bold text-indigo-400">Manual Transfer Instructions</h4>
                      <p className="text-sm">Please transfer exactly <b>Rp {(activeInvoice.amount || cost).toLocaleString('id-ID')}</b> to the bank below:</p>
                      <div className="grid gap-2 text-sm font-medium mt-2 bg-background/50 p-3 rounded-lg">
                        <div className="flex justify-between"><span>Bank:</span> <span>{activeInvoice.bank_details.bank_name}</span></div>
                        <div className="flex justify-between"><span>Account Number:</span> <span className="font-black text-indigo-300">{activeInvoice.bank_details.account_number}</span></div>
                        <div className="flex justify-between"><span>Account Holder:</span> <span>{activeInvoice.bank_details.account_holder}</span></div>
                      </div>
                      {activeInvoice.bank_details.whatsapp_number && (
                        <div className="pt-2">
                          <a 
                            href={`https://wa.me/${activeInvoice.bank_details.whatsapp_number.replace(/[^0-9]/g, '')}?text=Halo%20Admin,%20saya%20ingin%20konfirmasi%20pembayaran%20manual%20untuk%20Invoice%20${activeInvoice.invoice_id}%20sebesar%20Rp%20${(activeInvoice.amount || cost).toLocaleString('id-ID')}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex items-center justify-center gap-2 w-full px-4 py-2.5 text-sm font-bold text-white bg-green-600 hover:bg-green-700 rounded-xl shadow-md transition-all"
                          >
                            <MessageSquare className="h-4 w-4" /> Konfirmasi via WhatsApp
                          </a>
                        </div>
                      )}
                    </div>

                    <form onSubmit={handleUploadReceipt} className="space-y-3">
                      <Label htmlFor="receipt">Upload Payment Receipt</Label>
                      <div className="flex items-center gap-2">
                        <Input
                          id="receipt"
                          type="file"
                          accept="image/*"
                          onChange={(e) => setReceiptFile(e.target.files?.[0] || null)}
                          required
                        />
                        <Button type="submit" disabled={processing} className="bg-indigo-600">
                          <Upload className="h-4 w-4 mr-1" /> Submit
                        </Button>
                      </div>
                    </form>
                  </div>
                )}

                {activeInvoice.payment_method === 'tripay' && activeInvoice.tripay_data && (
                  <div className="space-y-4">
                    <div className="p-4 rounded-xl border border-emerald-500/20 bg-emerald-500/5 space-y-2">
                      <h4 className="font-bold text-emerald-400">Tripay Checkout Details</h4>
                      <p className="text-sm">Invoice is created on {activeInvoice.tripay_data.payment_name}.</p>
                      <div className="grid gap-2 text-sm font-medium mt-2 bg-background/50 p-3 rounded-lg">
                        <div className="flex justify-between"><span>Payment Method:</span> <span>{activeInvoice.tripay_data.payment_name}</span></div>
                        <div className="flex justify-between"><span>Amount:</span> <span>Rp {activeInvoice.tripay_data.amount?.toLocaleString('id-ID')}</span></div>
                        {activeInvoice.tripay_data.pay_code && (
                          <div className="flex justify-between"><span>Payment Code / VA:</span> <span className="font-black text-emerald-300">{activeInvoice.tripay_data.pay_code}</span></div>
                        )}
                        <div className="flex justify-between"><span>Reference Code:</span> <span>{activeInvoice.tripay_data.reference}</span></div>
                      </div>
                      
                      <div className="flex flex-col gap-2 pt-4">
                        <p className="text-xs text-muted-foreground">Since this is sandbox/local testing, you can instantly simulate a PAID webhook below:</p>
                        <Button type="button" onClick={handleSimulateTripayPaid} disabled={processing} className="w-full bg-emerald-600 hover:bg-emerald-500">
                          Simulate Tripay Callback (PAID)
                        </Button>
                      </div>
                    </div>
                  </div>
                )}

                {activeInvoice.payment_method === 'paypal' && (
                  <div className="space-y-4">
                    <div className="p-4 rounded-xl border border-blue-500/20 bg-blue-500/5 space-y-2">
                      <h4 className="font-bold text-blue-400">PayPal Checkout Details</h4>
                      <p className="text-sm">Paypal Order ID: <b>{activeInvoice.paypal_order_id}</b></p>
                      <p className="text-sm">Total to pay: <b>${activeInvoice.amount_usd} USD</b></p>
                      
                      <div className="flex flex-col gap-2 pt-4">
                        <p className="text-xs text-muted-foreground">Since this is sandbox/local testing, you can simulate a successful PayPal order capture below:</p>
                        <Button type="button" onClick={handleSimulatePayPal} disabled={processing} className="w-full bg-blue-600 hover:bg-blue-500">
                          Simulate PayPal Capture & Complete
                        </Button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Transaction History Table */}
      <Card className="border-border/50 shadow-md">
        <CardHeader>
          <CardTitle>Payment History</CardTitle>
          <CardDescription>Review all your credit transactions and manual upload forms.</CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full text-sm text-left border-collapse">
            <thead>
              <tr className="border-b bg-muted/40 font-semibold text-muted-foreground">
                <th className="p-4">Invoice ID</th>
                <th className="p-4">Date</th>
                <th className="p-4">Method</th>
                <th className="p-4 text-right">Credits</th>
                <th className="p-4 text-right">Total (IDR)</th>
                <th className="p-4">Status</th>
                <th className="p-4 text-center">Receipt Action</th>
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
                    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold ${
                      tx.status === 'success' ? 'bg-green-500/15 text-green-500' :
                      tx.status === 'awaiting_approval' ? 'bg-indigo-500/15 text-indigo-500' :
                      tx.status === 'pending' ? 'bg-yellow-500/15 text-yellow-500' :
                      'bg-red-500/15 text-red-500'
                    }`}>
                      {tx.status === 'awaiting_approval' ? 'Awaiting Admin' : tx.status}
                    </span>
                  </td>
                  <td className="p-4 text-center">
                    {tx.status === 'pending' && tx.payment_method === 'manual' ? (
                      <div className="flex justify-center">
                        <Button 
                          size="sm" 
                          variant="outline" 
                          className="h-8 text-xs bg-indigo-50 hover:bg-indigo-100 text-indigo-700 border-indigo-200"
                          onClick={() => {
                            setCreditsCount(tx.credits_purchased);
                            setActiveInvoice({
                              invoice_id: tx.invoice_id,
                              payment_method: tx.payment_method,
                              amount: tx.amount,
                              bank_details: tx.bank_details
                            });
                            window.scrollTo({ top: 0, behavior: 'smooth' });
                          }}
                        >
                          <Eye className="h-3 w-3 mr-1" /> View Invoice
                        </Button>
                      </div>
                    ) : tx.receipt_url ? (
                      <a href={tx.receipt_url} target="_blank" rel="noreferrer" className="inline-flex items-center text-xs text-indigo-400 hover:underline gap-1">
                        <Eye className="h-3 w-3" /> View Receipt
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
                    No transactions found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}
