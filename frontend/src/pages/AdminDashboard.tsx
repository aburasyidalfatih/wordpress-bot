import { useState, useEffect } from 'react';
import { Shield, Users, DollarSign, ListTodo, Eye, Trash2, Check, X, RefreshCw } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { toast } from 'sonner';
import { apiFetch } from '../lib/api';

export default function AdminDashboard() {
  const [stats, setStats] = useState<any>({});
  const [users, setUsers] = useState<any[]>([]);
  const [pendingPayments, setPendingPayments] = useState<any[]>([]);
  const [logs, setLogs] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState<string>('overview');
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [config, setConfig] = useState<any>({});

  // Edit user state
  const [editingUserId, setEditingUserId] = useState<number | null>(null);
  const [editRole, setEditRole] = useState<string>('user');
  const [editTier, setEditTier] = useState<string>('free');
  const [editCredits, setEditCredits] = useState<number>(0);
  const [editActive, setEditActive] = useState<boolean>(true);

  const fetchAdminData = async () => {
    try {
      const [statsRes, usersRes, paymentsRes, logsRes, configRes] = await Promise.all([
        apiFetch('/api/admin/stats'),
        apiFetch('/api/admin/users'),
        apiFetch('/api/admin/pending-payments'),
        apiFetch('/api/admin/logs?limit=300'),
        apiFetch('/api/admin/config')
      ]);

      const statsData = await statsRes.json();
      const usersData = await usersRes.json();
      const paymentsData = await paymentsRes.json();
      const logsData = await logsRes.json();
      const configData = await configRes.json();

      if (statsData.success) setStats(statsData.stats);
      if (usersData.success) setUsers(usersData.users);
      if (paymentsData.success) setPendingPayments(paymentsData.transactions);
      if (logsData.success) setLogs(logsData.logs || []);
      if (configData.success) setConfig(configData.config || {});
    } catch (e) {
      console.error(e);
      toast.error('Failed to retrieve administrative data.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchAdminData();
  }, []);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchAdminData();
  };

  // Payment approval handlers
  const handleApprovePayment = async (txId: number) => {
    if (!confirm('Are you sure you want to approve this payment? It will credit the user immediately.')) return;
    try {
      const res = await apiFetch(`/api/admin/payments/${txId}/approve`, { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        toast.success(data.message || 'Payment approved!');
        fetchAdminData();
      } else {
        toast.error(data.error || 'Failed to approve');
      }
    } catch (e) {
      toast.error('Network error during approval');
    }
  };

  const handleRejectPayment = async (txId: number) => {
    if (!confirm('Are you sure you want to reject this payment?')) return;
    try {
      const res = await apiFetch(`/api/admin/payments/${txId}/reject`, { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        toast.success('Payment rejected');
        fetchAdminData();
      } else {
        toast.error(data.error || 'Failed to reject');
      }
    } catch (e) {
      toast.error('Network error during rejection');
    }
  };

  // User management handlers
  const startEditUser = (user: any) => {
    setEditingUserId(user.id);
    setEditRole(user.role);
    setEditTier(user.tier);
    setEditCredits(user.credits);
    setEditActive(user.is_active);
  };

  const handleSaveUser = async (userId: number) => {
    try {
      const res = await apiFetch(`/api/admin/users/${userId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          role: editRole,
          tier: editTier,
          credits: editCredits,
          is_active: editActive
        })
      });
      const data = await res.json();
      if (data.success) {
        toast.success('User updated successfully');
        setEditingUserId(null);
        fetchAdminData();
      } else {
        toast.error(data.error || 'Failed to update user');
      }
    } catch (e) {
      toast.error('Network error updating user');
    }
  };

  const handleDeleteUser = async (userId: number) => {
    if (!confirm('WARNING: Cascade deleting this user will destroy all their WordPress configurations, posted article logs, and payment entries. Do you wish to proceed?')) return;
    try {
      const res = await apiFetch(`/api/admin/users/${userId}`, { method: 'DELETE' });
      const data = await res.json();
      if (data.success) {
        toast.success('User deleted successfully');
        fetchAdminData();
      } else {
        toast.error(data.error || 'Failed to delete user');
      }
    } catch (e) {
      toast.error('Network error deleting user');
    }
  };

  const handleSaveConfig = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await apiFetch('/api/admin/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });
      const data = await res.json();
      if (data.success) {
        toast.success('Configurations updated successfully');
      } else {
        toast.error(data.error || 'Failed to update configurations');
      }
    } catch (err) {
      toast.error('Network error updating configurations');
    }
  };

  if (loading) return <div className="p-8">Loading administration dashboard...</div>;

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-primary to-indigo-600 dark:from-primary dark:to-indigo-400 bg-clip-text text-transparent flex items-center gap-2">
            <Shield className="h-8 w-8 text-primary" /> Admin Control
          </h1>
          <p className="text-muted-foreground">Manage multi-tenant users, verify bank transfers, and check daemon processes.</p>
        </div>
        <Button variant="outline" size="sm" onClick={handleRefresh} disabled={refreshing} className="gap-2">
          <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} /> Refresh Data
        </Button>
      </div>

      {/* Tabs Menu */}
      <div className="flex border-b border-border gap-2">
        {['overview', 'users', 'payments', 'settings', 'logs'].map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm font-semibold capitalize border-b-2 transition-all -mb-px ${
              activeTab === tab 
                ? 'border-primary text-primary' 
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
          >
            {tab === 'payments' 
              ? `Payments (${pendingPayments.length})` 
              : tab === 'settings' 
                ? 'Admin Settings' 
                : tab}
          </button>
        ))}
      </div>

      {/* 1. Overview Tab */}
      {activeTab === 'overview' && (
        <div className="grid gap-6 sm:grid-cols-2 md:grid-cols-3">
          <Card className="border-border/50 shadow-md">
            <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
              <CardTitle className="text-sm font-medium">Total Registered Users</CardTitle>
              <Users className="h-4 w-4 text-indigo-500" />
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-black">{stats.total_users || 0}</div>
              <p className="text-xs text-muted-foreground mt-1">Including {stats.total_pro || 0} Pro tier users</p>
            </CardContent>
          </Card>

          <Card className="border-border/50 shadow-md">
            <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
              <CardTitle className="text-sm font-medium">Total Earnings (IDR)</CardTitle>
              <DollarSign className="h-4 w-4 text-emerald-500" />
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-black">Rp {stats.total_earnings_idr?.toLocaleString('id-ID') || 0}</div>
              <p className="text-xs text-muted-foreground mt-1">From {stats.total_credits_purchased || 0} credits purchased</p>
            </CardContent>
          </Card>

          <Card className="border-border/50 shadow-md">
            <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
              <CardTitle className="text-sm font-medium">Auto-post Queue & Logs</CardTitle>
              <ListTodo className="h-4 w-4 text-blue-500" />
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-black">{stats.queue_count || 0} Items</div>
              <p className="text-xs text-muted-foreground mt-1">Total articles posted to WordPress: {stats.total_articles || 0}</p>
            </CardContent>
          </Card>
        </div>
      )}

      {/* 2. User Management Tab */}
      {activeTab === 'users' && (
        <Card className="border-border/50 shadow-md">
          <CardHeader>
            <CardTitle>User Directory</CardTitle>
            <CardDescription>Manage user access levels, available credits, and edit active parameters.</CardDescription>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full text-sm text-left border-collapse">
              <thead>
                <tr className="border-b bg-muted/40 font-semibold text-muted-foreground">
                  <th className="p-4">ID</th>
                  <th className="p-4">Name</th>
                  <th className="p-4">Email</th>
                  <th className="p-4">Role</th>
                  <th className="p-4">Tier</th>
                  <th className="p-4 text-right">Credits</th>
                  <th className="p-4">Status</th>
                  <th className="p-4 text-center">Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => {
                  const isEditing = editingUserId === user.id;
                  return (
                    <tr key={user.id} className="border-b hover:bg-secondary/20 transition-colors">
                      <td className="p-4 font-mono text-xs">{user.id}</td>
                      <td className="p-4 font-medium">{user.name}</td>
                      <td className="p-4 font-mono text-xs text-muted-foreground">{user.email}</td>
                      <td className="p-4 capitalize">
                        {isEditing ? (
                          <select 
                            value={editRole} 
                            onChange={(e) => setEditRole(e.target.value)}
                            className="h-8 rounded border bg-background px-2"
                          >
                            <option value="user">User</option>
                            <option value="admin">Admin</option>
                          </select>
                        ) : (
                          <span className={`px-2 py-0.5 rounded text-xs font-bold ${user.role === 'admin' ? 'bg-primary/20 text-primary' : 'bg-secondary text-muted-foreground'}`}>{user.role}</span>
                        )}
                      </td>
                      <td className="p-4 capitalize">
                        {isEditing ? (
                          <select 
                            value={editTier} 
                            onChange={(e) => setEditTier(e.target.value)}
                            className="h-8 rounded border bg-background px-2"
                          >
                            <option value="free">Free</option>
                            <option value="pro">Pro</option>
                          </select>
                        ) : (
                          user.tier
                        )}
                      </td>
                      <td className="p-4 text-right font-bold text-primary">
                        {isEditing ? (
                          <Input 
                            type="number" 
                            className="h-8 w-20 text-right inline-block" 
                            value={editCredits} 
                            onChange={(e) => setEditCredits(parseInt(e.target.value) || 0)} 
                          />
                        ) : (
                          user.credits
                        )}
                      </td>
                      <td className="p-4">
                        {isEditing ? (
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              onClick={() => setEditActive(!editActive)}
                              className={`${editActive ? 'bg-primary' : 'bg-muted'} relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none`}
                            >
                              <span
                                className={`${editActive ? 'translate-x-4' : 'translate-x-0'} pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out`}
                              />
                            </button>
                            <span className="text-xs font-semibold">{editActive ? 'Active' : 'Suspended'}</span>
                          </div>
                        ) : (
                          <span className={`inline-flex px-2 py-0.5 text-xs font-bold rounded-full ${user.is_active ? 'bg-green-500/15 text-green-500' : 'bg-red-500/15 text-red-500'}`}>
                            {user.is_active ? 'Active' : 'Suspended'}
                          </span>
                        )}
                      </td>
                      <td className="p-4 text-center">
                        <div className="flex items-center justify-center gap-2">
                          {isEditing ? (
                            <>
                              <Button size="sm" onClick={() => handleSaveUser(user.id)} className="h-8 bg-green-600 hover:bg-green-500 px-3">
                                <Check className="h-4 w-4" /> Save
                              </Button>
                              <Button size="sm" variant="ghost" onClick={() => setEditingUserId(null)} className="h-8 px-3">
                                Cancel
                              </Button>
                            </>
                          ) : (
                            <>
                              <Button size="sm" variant="outline" onClick={() => startEditUser(user)} className="h-8 text-xs">
                                Edit
                              </Button>
                              <Button size="sm" variant="destructive" onClick={() => handleDeleteUser(user.id)} className="h-8 text-xs gap-1">
                                <Trash2 className="h-3.5 w-3.5" /> Delete
                              </Button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {/* 3. Payment Approvals Tab */}
      {activeTab === 'payments' && (
        <Card className="border-border/50 shadow-md">
          <CardHeader>
            <CardTitle>Pending Manual Approvals</CardTitle>
            <CardDescription>Verify user receipts and deposit credits instantly.</CardDescription>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full text-sm text-left border-collapse">
              <thead>
                <tr className="border-b bg-muted/40 font-semibold text-muted-foreground">
                  <th className="p-4">Invoice ID</th>
                  <th className="p-4">Date</th>
                  <th className="p-4">User</th>
                  <th className="p-4 text-right">Credits Request</th>
                  <th className="p-4 text-right">Amount (IDR)</th>
                  <th className="p-4 text-center">Receipt</th>
                  <th className="p-4 text-center">Actions</th>
                </tr>
              </thead>
              <tbody>
                {pendingPayments.map((tx) => (
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
                          <Eye className="h-4 w-4" /> View Receipt
                        </a>
                      ) : (
                        <span className="text-xs text-yellow-500 font-medium">Receipt missing</span>
                      )}
                    </td>
                    <td className="p-4 text-center">
                      <div className="flex items-center justify-center gap-2">
                        <Button 
                          size="sm" 
                          onClick={() => handleApprovePayment(tx.id)} 
                          className="h-8 bg-green-600 hover:bg-green-500 gap-1 px-3 text-xs"
                          disabled={!tx.receipt_url}
                        >
                          <Check className="h-3.5 w-3.5" /> Approve
                        </Button>
                        <Button 
                          size="sm" 
                          variant="destructive" 
                          onClick={() => handleRejectPayment(tx.id)} 
                          className="h-8 gap-1 px-3 text-xs"
                        >
                          <X className="h-3.5 w-3.5" /> Reject
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
                {pendingPayments.length === 0 && (
                  <tr>
                    <td colSpan={7} className="p-8 text-center text-muted-foreground font-medium">
                      No pending payment approvals found.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {/* 4. Logs Console Tab */}
      {activeTab === 'logs' && (
        <Card className="border-border/50 shadow-md">
          <CardHeader>
            <CardTitle>System Logs Console</CardTitle>
            <CardDescription>Stdout tail of daemon process logger `bot.log`.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-96 w-full rounded-lg bg-black text-green-400 font-mono text-xs overflow-y-auto p-4 border shadow-inner">
              {logs.map((line, idx) => (
                <div key={idx} className="whitespace-pre-wrap leading-relaxed py-0.5 border-b border-green-950/20 hover:bg-green-950/15">
                  {line}
                </div>
              ))}
              {logs.length === 0 && <div className="text-muted-foreground text-center pt-10">No log entries found.</div>}
            </div>
          </CardContent>
        </Card>
      )}

      {/* 5. Settings Tab */}
      {activeTab === 'settings' && (
        <form onSubmit={handleSaveConfig} className="space-y-6">
          <div className="grid gap-6 md:grid-cols-2">
            
            {/* Payment Settings */}
            <Card className="border-border/50 shadow-md">
              <CardHeader>
                <CardTitle className="text-lg flex items-center gap-2">
                  <DollarSign className="h-5 w-5 text-indigo-500" /> Payment Settings
                </CardTitle>
                <CardDescription>Configure Tripay and PayPal credentials for top-up purchases.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="PAYMENT_USD_RATE">USD conversion rate (IDR)</Label>
                  <Input 
                    id="PAYMENT_USD_RATE"
                    type="number"
                    value={config.PAYMENT_USD_RATE || 16000}
                    onChange={(e) => setConfig({ ...config, PAYMENT_USD_RATE: parseFloat(e.target.value) || 0 })}
                    placeholder="e.g. 16000"
                    required
                  />
                </div>
                <div className="h-px bg-border my-2" />
                <div className="flex items-center justify-between">
                  <h4 className="font-semibold text-sm text-foreground/85">Tripay (IDR Gateway)</h4>
                  <button
                    type="button"
                    onClick={() => setConfig({ ...config, PAYMENT_TRIPAY_ENABLED: config.PAYMENT_TRIPAY_ENABLED !== false ? false : true })}
                    className={`${config.PAYMENT_TRIPAY_ENABLED !== false ? 'bg-primary' : 'bg-muted'} relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none`}
                  >
                    <span
                      className={`${config.PAYMENT_TRIPAY_ENABLED !== false ? 'translate-x-4' : 'translate-x-0'} pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out`}
                    />
                  </button>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="TRIPAY_MERCHANT_CODE">Merchant Code</Label>
                    <Input 
                      id="TRIPAY_MERCHANT_CODE"
                      value={config.TRIPAY_MERCHANT_CODE || ''}
                      onChange={(e) => setConfig({ ...config, TRIPAY_MERCHANT_CODE: e.target.value })}
                      placeholder="T12345"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="TRIPAY_API_URL">API URL</Label>
                    <Input 
                      id="TRIPAY_API_URL"
                      value={config.TRIPAY_API_URL || ''}
                      onChange={(e) => setConfig({ ...config, TRIPAY_API_URL: e.target.value })}
                      placeholder="https://tripay.co.id/api-sandbox"
                    />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="TRIPAY_API_KEY">API Key</Label>
                  <Input 
                    id="TRIPAY_API_KEY"
                    type="password"
                    value={config.TRIPAY_API_KEY || ''}
                    onChange={(e) => setConfig({ ...config, TRIPAY_API_KEY: e.target.value })}
                    placeholder={config.has_TRIPAY_API_KEY ? "Sudah tersimpan. Isi untuk mengganti." : "Your Tripay API Key"}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="TRIPAY_PRIVATE_KEY">Private Key</Label>
                  <Input 
                    id="TRIPAY_PRIVATE_KEY"
                    type="password"
                    value={config.TRIPAY_PRIVATE_KEY || ''}
                    onChange={(e) => setConfig({ ...config, TRIPAY_PRIVATE_KEY: e.target.value })}
                    placeholder={config.has_TRIPAY_PRIVATE_KEY ? "Sudah tersimpan. Isi untuk mengganti." : "Your Tripay Private Key"}
                  />
                </div>
                <div className="h-px bg-border my-2" />
                <div className="flex items-center justify-between">
                  <h4 className="font-semibold text-sm text-foreground/85">PayPal (USD Gateway)</h4>
                  <button
                    type="button"
                    onClick={() => setConfig({ ...config, PAYMENT_PAYPAL_ENABLED: config.PAYMENT_PAYPAL_ENABLED !== false ? false : true })}
                    className={`${config.PAYMENT_PAYPAL_ENABLED !== false ? 'bg-primary' : 'bg-muted'} relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none`}
                  >
                    <span
                      className={`${config.PAYMENT_PAYPAL_ENABLED !== false ? 'translate-x-4' : 'translate-x-0'} pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out`}
                    />
                  </button>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="PAYPAL_API_URL">API URL</Label>
                    <Input 
                      id="PAYPAL_API_URL"
                      value={config.PAYPAL_API_URL || ''}
                      onChange={(e) => setConfig({ ...config, PAYPAL_API_URL: e.target.value })}
                      placeholder="https://api-m.sandbox.paypal.com"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="PAYPAL_CLIENT_ID">Client ID</Label>
                    <Input 
                      id="PAYPAL_CLIENT_ID"
                      value={config.PAYPAL_CLIENT_ID || ''}
                      onChange={(e) => setConfig({ ...config, PAYPAL_CLIENT_ID: e.target.value })}
                      placeholder="PayPal Client ID"
                    />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="PAYPAL_SECRET">Secret</Label>
                  <Input 
                    id="PAYPAL_SECRET"
                    type="password"
                    value={config.PAYPAL_SECRET || ''}
                    onChange={(e) => setConfig({ ...config, PAYPAL_SECRET: e.target.value })}
                    placeholder={config.has_PAYPAL_SECRET ? "Sudah tersimpan. Isi untuk mengganti." : "PayPal Secret Key"}
                  />
                </div>
                <div className="h-px bg-border my-2" />
                <div className="flex items-center justify-between">
                  <h4 className="font-semibold text-sm text-foreground/85">Manual Bank Account (Local Gateway)</h4>
                  <button
                    type="button"
                    onClick={() => setConfig({ ...config, PAYMENT_MANUAL_ENABLED: config.PAYMENT_MANUAL_ENABLED !== false ? false : true })}
                    className={`${config.PAYMENT_MANUAL_ENABLED !== false ? 'bg-primary' : 'bg-muted'} relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none`}
                  >
                    <span
                      className={`${config.PAYMENT_MANUAL_ENABLED !== false ? 'translate-x-4' : 'translate-x-0'} pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out`}
                    />
                  </button>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="MANUAL_BANK_NAME">Bank Name</Label>
                    <Input 
                      id="MANUAL_BANK_NAME"
                      value={config.MANUAL_BANK_NAME || ''}
                      onChange={(e) => setConfig({ ...config, MANUAL_BANK_NAME: e.target.value })}
                      placeholder="e.g. Bank Mandiri"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="MANUAL_BANK_HOLDER">Account Holder Name</Label>
                    <Input 
                      id="MANUAL_BANK_HOLDER"
                      value={config.MANUAL_BANK_HOLDER || ''}
                      onChange={(e) => setConfig({ ...config, MANUAL_BANK_HOLDER: e.target.value })}
                      placeholder="e.g. ADMIN AUTOWP"
                    />
                  </div>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="MANUAL_BANK_ACCOUNT">Account Number</Label>
                    <Input 
                      id="MANUAL_BANK_ACCOUNT"
                      value={config.MANUAL_BANK_ACCOUNT || ''}
                      onChange={(e) => setConfig({ ...config, MANUAL_BANK_ACCOUNT: e.target.value })}
                      placeholder="e.g. 123-456-789"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="ADMIN_WHATSAPP">Wa Confirmation</Label>
                    <Input 
                      id="ADMIN_WHATSAPP"
                      value={config.ADMIN_WHATSAPP || ''}
                      onChange={(e) => setConfig({ ...config, ADMIN_WHATSAPP: e.target.value })}
                      placeholder="e.g. 628123456789"
                    />
                  </div>
                </div>
              </CardContent>
            </Card>
            
            <div className="space-y-6">
              {/* Gemini AI Settings */}
              <Card className="border-border/50 shadow-md">
                <CardHeader>
                  <CardTitle className="text-lg flex items-center gap-2">
                    <Shield className="h-5 w-5 text-indigo-500" /> Gemini AI Configuration
                  </CardTitle>
                  <CardDescription>Configure Google Gemini API for shared content generation.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="gemini_api_key">API Key</Label>
                    <Input 
                      id="gemini_api_key"
                      type="password"
                      value={config.gemini_api_key || ''}
                      onChange={(e) => setConfig({ ...config, gemini_api_key: e.target.value })}
                      placeholder={config.has_gemini_api_key ? "Sudah tersimpan. Isi untuk mengganti." : "Your Gemini API Key"}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="gemini_model">Text Model</Label>
                    <select 
                      id="gemini_model"
                      value={config.gemini_model || 'gemini-3.5-flash'}
                      onChange={(e) => setConfig({ ...config, gemini_model: e.target.value })}
                      className="flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <option value="gemini-3.5-flash">Gemini 3.5 Flash (Recommended)</option>
                      <option value="gemini-3.5-pro">Gemini 3.5 Pro</option>
                      <option value="gemini-3.1-flash-lite">Gemini 3.1 Flash-Lite</option>
                      <option value="gemini-3.1-pro">Gemini 3.1 Pro</option>
                      <option value="gemini-2.5-pro">Gemini 2.5 Pro (Legacy)</option>
                      <option value="gemini-1.5-flash">Gemini 1.5 Flash (Legacy)</option>
                    </select>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="gemini_image_model">Image Model</Label>
                    <select 
                      id="gemini_image_model"
                      value={config.gemini_image_model || 'imagen-4.0-generate-001'}
                      onChange={(e) => setConfig({ ...config, gemini_image_model: e.target.value })}
                      className="flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <option value="gemini-3.1-flash-image">Gemini 3.1 Flash Image (Recommended / API Key Compatible)</option>
                      <option value="gemini-3-pro-image">Gemini 3 Pro Image (High Quality)</option>
                      <option value="gemini-2.5-flash-image">Gemini 2.5 Flash Image (Stable)</option>
                      <option value="imagen-3.0-generate-001">Imagen 3.0 Generate (Legacy / OAuth 2.0 Only)</option>
                    </select>
                  </div>
                </CardContent>
              </Card>

              {/* Google Settings */}
              <Card className="border-border/50 shadow-md">
                <CardHeader>
                  <CardTitle className="text-lg flex items-center gap-2">
                    <Shield className="h-5 w-5 text-indigo-500" /> Google OAuth
                  </CardTitle>
                  <CardDescription>Configure Google Client ID and Secret to enable Google Login.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="GOOGLE_CLIENT_ID">Google Client ID</Label>
                    <Input 
                      id="GOOGLE_CLIENT_ID"
                      value={config.GOOGLE_CLIENT_ID || ''}
                      onChange={(e) => setConfig({ ...config, GOOGLE_CLIENT_ID: e.target.value })}
                      placeholder="Your Google Client ID"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="GOOGLE_CLIENT_SECRET">Google Client Secret</Label>
                    <Input 
                      id="GOOGLE_CLIENT_SECRET"
                      type="password"
                      value={config.GOOGLE_CLIENT_SECRET || ''}
                      onChange={(e) => setConfig({ ...config, GOOGLE_CLIENT_SECRET: e.target.value })}
                      placeholder={config.has_GOOGLE_CLIENT_SECRET ? "Sudah tersimpan. Isi untuk mengganti." : "Your Google Client Secret"}
                    />
                  </div>
                </CardContent>
              </Card>

              {/* Notification Settings */}
              <Card className="border-border/50 shadow-md">
                <CardHeader>
                  <CardTitle className="text-lg flex items-center gap-2">
                    <Users className="h-5 w-5 text-indigo-500" /> Notifications Setting
                  </CardTitle>
                  <CardDescription>Configure SMTP Mailketing and Starsender WhatsApp Gateway.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <h4 className="font-semibold text-sm text-foreground/85">SMTP Mailketing</h4>
                  <div className="grid gap-4 sm:grid-cols-3">
                    <div className="space-y-2 sm:col-span-2">
                      <Label htmlFor="SMTP_HOST">SMTP Host</Label>
                      <Input 
                        id="SMTP_HOST"
                        value={config.SMTP_HOST || ''}
                        onChange={(e) => setConfig({ ...config, SMTP_HOST: e.target.value })}
                        placeholder="smtp.mailketing.co.id"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="SMTP_PORT">SMTP Port</Label>
                      <Input 
                        id="SMTP_PORT"
                        type="number"
                        value={config.SMTP_PORT || 587}
                        onChange={(e) => setConfig({ ...config, SMTP_PORT: parseInt(e.target.value) || 0 })}
                        placeholder="587"
                      />
                    </div>
                  </div>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <div className="space-y-2">
                      <Label htmlFor="SMTP_USER">SMTP User</Label>
                      <Input 
                        id="SMTP_USER"
                        value={config.SMTP_USER || ''}
                        onChange={(e) => setConfig({ ...config, SMTP_USER: e.target.value })}
                        placeholder="Your SMTP username"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="SMTP_PASSWORD">SMTP Password</Label>
                      <Input 
                        id="SMTP_PASSWORD"
                        type="password"
                        value={config.SMTP_PASSWORD || ''}
                        onChange={(e) => setConfig({ ...config, SMTP_PASSWORD: e.target.value })}
                        placeholder={config.has_SMTP_PASSWORD ? "Sudah tersimpan. Isi untuk mengganti." : "Your SMTP password"}
                      />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="SMTP_SENDER_EMAIL">Sender Email</Label>
                    <Input 
                      id="SMTP_SENDER_EMAIL"
                      type="email"
                      value={config.SMTP_SENDER_EMAIL || ''}
                      onChange={(e) => setConfig({ ...config, SMTP_SENDER_EMAIL: e.target.value })}
                      placeholder="sender@yourdomain.com"
                    />
                  </div>

                  <div className="h-px bg-border my-2" />
                  <h4 className="font-semibold text-sm text-foreground/85">Starsender WA Gateway</h4>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <div className="space-y-2">
                      <Label htmlFor="STARSENDER_API_KEY">Starsender API Key</Label>
                      <Input 
                        id="STARSENDER_API_KEY"
                        type="password"
                        value={config.STARSENDER_API_KEY || ''}
                        onChange={(e) => setConfig({ ...config, STARSENDER_API_KEY: e.target.value })}
                        placeholder={config.has_STARSENDER_API_KEY ? "Sudah tersimpan. Isi untuk mengganti." : "Starsender API Key"}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="STARSENDER_DEVICE_ID">Device ID (Phone Number)</Label>
                      <Input 
                        id="STARSENDER_DEVICE_ID"
                        value={config.STARSENDER_DEVICE_ID || ''}
                        onChange={(e) => setConfig({ ...config, STARSENDER_DEVICE_ID: e.target.value })}
                        placeholder="e.g. 08123456789"
                      />
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* Submit Button */}
              <div className="flex justify-end">
                <Button type="submit" size="lg" className="w-full sm:w-auto font-bold bg-primary hover:bg-primary/95 text-white rounded-xl shadow-lg shadow-primary/20">
                  Save Settings
                </Button>
              </div>
            </div>

          </div>
        </form>
      )}
    </div>
  );
}
