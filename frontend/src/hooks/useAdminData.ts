import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { apiFetch, isAbortError, NETWORK_ERROR } from '@/lib/api';
import type { AdminConfig, AdminStats, AdminUser, PendingPayment } from '@/lib/types';

export interface AdminUserUpdate {
  role: string;
  tier: string;
  credits: number;
  is_active: boolean;
}

/** Runs an admin action request and shows its result as a toast. */
async function runAction(url: string, init: RequestInit, successMessage: string, failureMessage: string, preferServerMessage = false) {
  try {
    const res = await apiFetch(url, init);
    const data = await res.json();
    if (data.success) {
      toast.success((preferServerMessage && data.message) || successMessage);
      return true;
    }
    toast.error(data.error || failureMessage);
  } catch {
    toast.error(NETWORK_ERROR);
  }
  return false;
}

/** Data and actions of the admin dashboard. */
export function useAdminData() {
  const [stats, setStats] = useState<AdminStats>({});
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [pendingPayments, setPendingPayments] = useState<PendingPayment[]>([]);
  const [logs, setLogs] = useState<string[]>([]);
  const [config, setConfig] = useState<AdminConfig>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchAdminData = useCallback((signal?: AbortSignal) => {
    const endpoints = [
      '/api/admin/stats',
      '/api/admin/users',
      '/api/admin/pending-payments',
      '/api/admin/logs?limit=300',
      '/api/admin/config',
    ];
    return Promise.all(endpoints.map(url => apiFetch(url, { signal })))
      .then(responses => Promise.all(responses.map(res => res.json())))
      .then(([statsData, usersData, paymentsData, logsData, configData]) => {
        if (statsData.success) setStats(statsData.stats);
        if (usersData.success) setUsers(usersData.users);
        if (paymentsData.success) setPendingPayments(paymentsData.transactions);
        if (logsData.success) setLogs(logsData.logs || []);
        if (configData.success) setConfig(configData.config || {});
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) return;
        if (import.meta.env.DEV) console.error(error);
        toast.error('Gagal memuat data admin.');
      })
      .finally(() => {
        setLoading(false);
        setRefreshing(false);
      });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    fetchAdminData(controller.signal);
    return () => controller.abort();
  }, [fetchAdminData]);

  const refresh = () => {
    setRefreshing(true);
    fetchAdminData();
  };

  const approvePayment = async (txId: number) => {
    if (!confirm('Setujui pembayaran ini? Kredit akan langsung ditambahkan ke akun pengguna.')) return;
    if (await runAction(`/api/admin/payments/${txId}/approve`, { method: 'POST' }, 'Pembayaran disetujui.', 'Gagal menyetujui pembayaran.', true)) {
      fetchAdminData();
    }
  };

  const rejectPayment = async (txId: number) => {
    if (!confirm('Tolak pembayaran ini?')) return;
    if (await runAction(`/api/admin/payments/${txId}/reject`, { method: 'POST' }, 'Pembayaran ditolak.', 'Gagal menolak pembayaran.')) {
      fetchAdminData();
    }
  };

  /** Returns true when the user was saved. */
  const saveUser = async (userId: number, update: AdminUserUpdate) => {
    const saved = await runAction(`/api/admin/users/${userId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(update),
    }, 'Data pengguna berhasil diperbarui.', 'Gagal memperbarui pengguna.');
    if (saved) fetchAdminData();
    return saved;
  };

  const deleteUser = async (userId: number) => {
    if (!confirm('PERINGATAN: Menghapus pengguna ini juga akan menghapus seluruh konfigurasi WordPress, log artikel, dan riwayat pembayarannya. Lanjutkan?')) return;
    if (await runAction(`/api/admin/users/${userId}`, { method: 'DELETE' }, 'Pengguna berhasil dihapus.', 'Gagal menghapus pengguna.')) {
      fetchAdminData();
    }
  };

  const saveConfig = async (e: React.FormEvent) => {
    e.preventDefault();
    await runAction('/api/admin/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    }, 'Pengaturan berhasil disimpan.', 'Gagal menyimpan pengaturan.');
  };

  return {
    stats, users, pendingPayments, logs, config, setConfig, loading, refreshing,
    refresh, approvePayment, rejectPayment, saveUser, deleteUser, saveConfig,
  };
}
