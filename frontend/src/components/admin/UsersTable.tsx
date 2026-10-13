import { useState } from 'react';
import { Trash2, Check } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ToggleSwitch } from '@/components/ToggleSwitch';
import type { AdminUserUpdate } from '@/hooks/useAdminData';
import type { AdminUser } from '@/lib/types';

const ROLE_LABELS: Record<string, string> = { user: 'Pengguna', admin: 'Admin' };

interface UsersTableProps {
  users: AdminUser[];
  onSave: (userId: number, update: AdminUserUpdate) => Promise<boolean>;
  onDelete: (userId: number) => void;
}

export function UsersTable({ users, onSave, onDelete }: UsersTableProps) {
  const [editingUserId, setEditingUserId] = useState<number | null>(null);
  const [draft, setDraft] = useState<AdminUserUpdate>({ role: 'user', tier: 'free', credits: 0, is_active: true });

  const startEdit = (user: AdminUser) => {
    setEditingUserId(user.id);
    setDraft({ role: user.role, tier: user.tier, credits: user.credits, is_active: user.is_active });
  };

  const save = async (userId: number) => {
    if (await onSave(userId, draft)) setEditingUserId(null);
  };

  return (
    <Card className="border-border/50 shadow-md">
      <CardHeader>
        <CardTitle>Daftar Pengguna</CardTitle>
        <CardDescription>Kelola hak akses, kredit, dan status akun pengguna.</CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full text-sm text-left border-collapse">
          <thead>
            <tr className="border-b bg-muted/40 font-semibold text-muted-foreground">
              <th className="p-4">ID</th>
              <th className="p-4">Nama</th>
              <th className="p-4">Email</th>
              <th className="p-4">Peran</th>
              <th className="p-4">Tier</th>
              <th className="p-4 text-right">Kredit</th>
              <th className="p-4">Status</th>
              <th className="p-4 text-center">Aksi</th>
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
                      <select value={draft.role} onChange={(e) => setDraft({ ...draft, role: e.target.value })} className="h-8 rounded border bg-background px-2">
                        <option value="user">Pengguna</option>
                        <option value="admin">Admin</option>
                      </select>
                    ) : (
                      <span className={`px-2 py-0.5 rounded text-xs font-bold ${user.role === 'admin' ? 'bg-primary/20 text-primary' : 'bg-secondary text-muted-foreground'}`}>
                        {ROLE_LABELS[user.role] ?? user.role}
                      </span>
                    )}
                  </td>
                  <td className="p-4 capitalize">
                    {isEditing ? (
                      <select value={draft.tier} onChange={(e) => setDraft({ ...draft, tier: e.target.value })} className="h-8 rounded border bg-background px-2">
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
                        value={draft.credits}
                        onChange={(e) => setDraft({ ...draft, credits: parseInt(e.target.value) || 0 })}
                      />
                    ) : (
                      user.credits
                    )}
                  </td>
                  <td className="p-4">
                    {isEditing ? (
                      <div className="flex items-center gap-2">
                        <ToggleSwitch
                          size="sm"
                          checked={draft.is_active}
                          onToggle={() => setDraft({ ...draft, is_active: !draft.is_active })}
                          ariaLabel="Status akun"
                        />
                        <span className="text-xs font-semibold">{draft.is_active ? 'Aktif' : 'Ditangguhkan'}</span>
                      </div>
                    ) : (
                      <span className={`inline-flex px-2 py-0.5 text-xs font-bold rounded-full ${user.is_active ? 'bg-green-500/15 text-green-500' : 'bg-red-500/15 text-red-500'}`}>
                        {user.is_active ? 'Aktif' : 'Ditangguhkan'}
                      </span>
                    )}
                  </td>
                  <td className="p-4 text-center">
                    <div className="flex items-center justify-center gap-2">
                      {isEditing ? (
                        <>
                          <Button size="sm" onClick={() => save(user.id)} className="h-8 bg-green-600 hover:bg-green-500 px-3">
                            <Check className="h-4 w-4" /> Simpan
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setEditingUserId(null)} className="h-8 px-3">
                            Batal
                          </Button>
                        </>
                      ) : (
                        <>
                          <Button size="sm" variant="outline" onClick={() => startEdit(user)} className="h-8 text-xs">
                            Edit
                          </Button>
                          <Button size="sm" variant="destructive" onClick={() => onDelete(user.id)} className="h-8 text-xs gap-1">
                            <Trash2 className="h-3.5 w-3.5" /> Hapus
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
  );
}
