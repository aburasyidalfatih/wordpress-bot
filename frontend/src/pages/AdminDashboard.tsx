import { useState } from 'react';
import { Shield, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useAdminData } from '@/hooks/useAdminData';
import { AdminOverview } from '@/components/admin/AdminOverview';
import { UsersTable } from '@/components/admin/UsersTable';
import { PendingPaymentsTable } from '@/components/admin/PendingPaymentsTable';
import { SystemLogsCard } from '@/components/admin/SystemLogsCard';
import { PaymentSettingsCard } from '@/components/admin/PaymentSettingsCard';
import { AiSettingsCard } from '@/components/admin/AiSettingsCard';
import { GoogleOAuthSettingsCard, NotificationSettingsCard } from '@/components/admin/IntegrationSettingsCards';
import Monitor from './Monitor';

type AdminTab = 'overview' | 'users' | 'payments' | 'monitor' | 'settings' | 'logs';
const ADMIN_TABS: AdminTab[] = ['overview', 'users', 'payments', 'monitor', 'settings', 'logs'];

export default function AdminDashboard() {
  const admin = useAdminData();
  const [activeTab, setActiveTab] = useState<AdminTab>('overview');

  if (admin.loading) return <div className="p-8">Memuat dashboard admin...</div>;

  const tabLabels: Record<AdminTab, string> = {
    overview: 'Ringkasan',
    users: 'Pengguna',
    payments: `Pembayaran (${admin.pendingPayments.length})`,
    monitor: 'Monitor Sistem',
    settings: 'Pengaturan Admin',
    logs: 'Log',
  };
  const configProps = { config: admin.config, setConfig: admin.setConfig };

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-primary to-indigo-600 dark:from-primary dark:to-indigo-400 bg-clip-text text-transparent flex items-center gap-2">
            <Shield className="h-8 w-8 text-primary" /> Kontrol Admin
          </h1>
          <p className="text-muted-foreground">Kelola pengguna, verifikasi transfer bank, dan pantau proses latar belakang.</p>
        </div>
        <Button variant="outline" size="sm" onClick={admin.refresh} disabled={admin.refreshing} className="gap-2">
          <RefreshCw className={`h-4 w-4 ${admin.refreshing ? 'animate-spin' : ''}`} /> Muat Ulang Data
        </Button>
      </div>

      {/* Tabs Menu */}
      <div className="flex overflow-x-auto whitespace-nowrap border-b border-border gap-2 no-scrollbar">
        {ADMIN_TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm font-semibold border-b-2 transition-all -mb-px ${
              activeTab === tab
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground hover:bg-muted/50'
            }`}
          >
            {tabLabels[tab]}
          </button>
        ))}
      </div>

      {activeTab === 'overview' && <AdminOverview stats={admin.stats} />}

      {activeTab === 'users' && (
        <UsersTable users={admin.users} onSave={admin.saveUser} onDelete={admin.deleteUser} />
      )}

      {activeTab === 'payments' && (
        <PendingPaymentsTable payments={admin.pendingPayments} onApprove={admin.approvePayment} onReject={admin.rejectPayment} />
      )}

      {activeTab === 'monitor' && (
        <div className="border border-border/50 shadow-md bg-card rounded-xl p-6">
          <Monitor />
        </div>
      )}

      {activeTab === 'logs' && <SystemLogsCard logs={admin.logs} />}

      {activeTab === 'settings' && (
        <form onSubmit={admin.saveConfig} className="space-y-6">
          <div className="grid gap-6 md:grid-cols-2">
            <PaymentSettingsCard {...configProps} />
            <div className="space-y-6">
              <AiSettingsCard {...configProps} />
              <GoogleOAuthSettingsCard {...configProps} />
              <NotificationSettingsCard {...configProps} />
              <div className="flex justify-end">
                <Button type="submit" size="lg" className="w-full sm:w-auto font-bold bg-primary hover:bg-primary/95 text-white rounded-xl shadow-lg shadow-primary/20">
                  Simpan Pengaturan
                </Button>
              </div>
            </div>
          </div>
        </form>
      )}
    </div>
  );
}
