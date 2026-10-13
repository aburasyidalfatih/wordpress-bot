import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { apiFetch, isAbortError, NETWORK_ERROR } from '@/lib/api';
import type { BillingHistoryItem, BillingProfile, InvoiceData, PaymentMethod, PaymentMethodsEnabled } from '@/lib/types';

interface PayPalReturn {
  invoiceId: string;
  orderId: string | null;
  cancelled: boolean;
}

/** PayPal redirects back to /billing?paypal_invoice=...&token=<order id>&PayerID=... */
function readPayPalReturn(): PayPalReturn | null {
  const params = new URLSearchParams(window.location.search);
  const invoiceId = params.get('paypal_invoice');
  if (!invoiceId) return null;
  return { invoiceId, orderId: params.get('token'), cancelled: !!params.get('paypal_cancel') };
}

function willCapture(paypalReturn: PayPalReturn | null) {
  return !!paypalReturn && !paypalReturn.cancelled && !!paypalReturn.orderId;
}

function postJson(url: string, body: unknown, headers: Record<string, string> = {}) {
  return apiFetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify(body),
  }).then(res => res.json());
}

function defaultPaymentMethod(enabled: PaymentMethodsEnabled): PaymentMethod {
  if (enabled.manual) return 'manual';
  if (enabled.tripay) return 'tripay';
  if (enabled.paypal) return 'paypal';
  return '';
}

/** Credit balance, payment history and the invoice/payment flow of the billing page. */
export function useBilling() {
  const [profile, setProfile] = useState<BillingProfile>({});
  const [history, setHistory] = useState<BillingHistoryItem[]>([]);
  const [enabled, setEnabled] = useState<PaymentMethodsEnabled>({ manual: true, tripay: true, paypal: true });
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>('manual');
  const [loading, setLoading] = useState(true);
  const [activeInvoice, setActiveInvoice] = useState<InvoiceData | null>(null);
  const [paypalReturn] = useState(readPayPalReturn);
  // Starts true when we came back from PayPal: the capture begins on mount.
  const [processing, setProcessing] = useState(() => willCapture(paypalReturn));
  const paypalReturnHandled = useRef(false);

  const fetchBillingInfo = useCallback((signal?: AbortSignal) => {
    const urls = ['/api/profile', '/api/payments/history', '/api/auth/config'];
    return Promise.all(urls.map(url => apiFetch(url, { signal })))
      .then(responses => Promise.all(responses.map(res => res.json())))
      .then(([profileData, historyData, configData]) => {
        if (profileData.success) setProfile(profileData.profile);
        if (historyData.success) setHistory(historyData.history);
        if (configData.success) {
          const methods = {
            tripay: configData.payment_tripay_enabled !== false,
            paypal: configData.payment_paypal_enabled !== false,
            manual: configData.payment_manual_enabled !== false,
          };
          setEnabled(methods);
          setPaymentMethod(defaultPaymentMethod(methods));
        }
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) return;
        if (import.meta.env.DEV) console.error(error);
        toast.error('Gagal memuat data tagihan.');
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    fetchBillingInfo(controller.signal);
    return () => controller.abort();
  }, [fetchBillingInfo]);

  // Credits changed: refresh this page and the header credit badge (Layout listens for this).
  const refreshAfterCreditChange = useCallback(() => {
    fetchBillingInfo();
    window.dispatchEvent(new Event('refresh-profile'));
  }, [fetchBillingInfo]);

  const applyCaptureResult = useCallback((data: { success?: boolean; error?: string }) => {
    if (data.success) {
      toast.success('Pembayaran berhasil! Kredit telah ditambahkan.');
      setActiveInvoice(null);
      refreshAfterCreditChange();
    } else {
      toast.error(data.error || 'Gagal memproses pembayaran PayPal.');
    }
  }, [refreshAfterCreditChange]);

  const runPayPalCapture = useCallback((orderId: string, invoiceId: string) =>
    postJson('/api/payments/paypal-capture', { order_id: orderId, invoice_id: invoiceId })
      .then(applyCaptureResult)
      .catch(() => toast.error(NETWORK_ERROR))
      .finally(() => setProcessing(false)),
  [applyCaptureResult]);

  useEffect(() => {
    if (!paypalReturn || paypalReturnHandled.current) return;
    paypalReturnHandled.current = true;
    // Drop the query string so a reload doesn't try to capture again.
    window.history.replaceState(null, '', window.location.pathname);
    if (!willCapture(paypalReturn)) {
      toast.info('Pembayaran PayPal dibatalkan.');
      return;
    }
    runPayPalCapture(paypalReturn.orderId as string, paypalReturn.invoiceId);
  }, [paypalReturn, runPayPalCapture]);

  const createInvoice = async (creditsCount: number, paymentCode: string) => {
    if (creditsCount <= 0) {
      toast.error('Jumlah kredit harus lebih dari 0.');
      return;
    }
    setProcessing(true);
    try {
      const data = await postJson('/api/payments/create-invoice', {
        credits_count: creditsCount,
        payment_method: paymentMethod,
        payment_code: paymentMethod === 'tripay' ? paymentCode : undefined,
      });
      if (data.success) {
        setActiveInvoice(data);
        toast.success('Invoice berhasil dibuat.');
      } else {
        toast.error(data.error || 'Gagal membuat invoice.');
      }
    } catch {
      toast.error(NETWORK_ERROR);
    } finally {
      setProcessing(false);
    }
  };

  /** Mock mode only: capture the PayPal order without visiting PayPal. */
  const simulatePayPal = () => {
    if (!activeInvoice?.paypal_order_id) return;
    setProcessing(true);
    return runPayPalCapture(activeInvoice.paypal_order_id, activeInvoice.invoice_id);
  };

  /** Mock mode only: send a PAID Tripay callback for the active invoice. */
  const simulateTripayPaid = async () => {
    if (!activeInvoice?.tripay_data) return;
    setProcessing(true);
    try {
      const data = await postJson('/api/payments/webhook/tripay', {
        merchant_ref: activeInvoice.invoice_id,
        status: 'PAID',
        reference: activeInvoice.tripay_data.reference,
      }, { 'X-Callback-Signature': 'mock_signature' });
      if (data.success) {
        toast.success('Simulasi callback Tripay berhasil! Kredit telah ditambahkan.');
        setActiveInvoice(null);
        refreshAfterCreditChange();
      } else {
        toast.error(data.message || 'Simulasi callback Tripay gagal.');
      }
    } catch {
      toast.error(NETWORK_ERROR);
    } finally {
      setProcessing(false);
    }
  };

  /** Returns true when the receipt was uploaded. */
  const uploadReceipt = async (invoiceId: string, receiptFile: File | null) => {
    if (!receiptFile) {
      toast.error('Pilih file bukti transfer terlebih dahulu.');
      return false;
    }
    setProcessing(true);
    const formData = new FormData();
    formData.append('invoice_id', invoiceId);
    formData.append('receipt', receiptFile);
    try {
      const res = await apiFetch('/api/payments/upload-receipt', { method: 'POST', body: formData });
      const data = await res.json();
      if (data.success) {
        toast.success(data.message || 'Bukti transfer berhasil diunggah.');
        setActiveInvoice(null);
        fetchBillingInfo();
        return true;
      }
      toast.error(data.error || 'Gagal mengunggah bukti transfer.');
    } catch {
      toast.error(NETWORK_ERROR);
    } finally {
      setProcessing(false);
    }
    return false;
  };

  return {
    profile, history, enabled, paymentMethod, setPaymentMethod, loading, processing,
    activeInvoice, setActiveInvoice, createInvoice, simulatePayPal, simulateTripayPaid, uploadReceipt,
  };
}
