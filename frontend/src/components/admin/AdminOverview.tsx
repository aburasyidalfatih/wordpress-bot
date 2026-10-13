import type { ReactNode } from 'react';
import { Users, DollarSign, ListTodo } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { AdminStats } from '@/lib/types';

function StatCard({ title, icon, value, note }: { title: string; icon: ReactNode; value: ReactNode; note: ReactNode }) {
  return (
    <Card className="border-border/50 shadow-md">
      <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        {icon}
      </CardHeader>
      <CardContent>
        <div className="text-3xl font-black">{value}</div>
        <p className="text-xs text-muted-foreground mt-1">{note}</p>
      </CardContent>
    </Card>
  );
}

export function AdminOverview({ stats }: { stats: AdminStats }) {
  return (
    <div className="grid gap-6 sm:grid-cols-2 md:grid-cols-3">
      <StatCard
        title="Total Pengguna Terdaftar"
        icon={<Users className="h-4 w-4 text-indigo-500" />}
        value={stats.total_users || 0}
        note={`Termasuk ${stats.total_pro || 0} pengguna tier Pro`}
      />
      <StatCard
        title="Total Pendapatan (IDR)"
        icon={<DollarSign className="h-4 w-4 text-emerald-500" />}
        value={`Rp ${stats.total_earnings_idr?.toLocaleString('id-ID') || 0}`}
        note={`Dari ${stats.total_credits_purchased || 0} kredit terjual`}
      />
      <StatCard
        title="Antrean & Log Auto-post"
        icon={<ListTodo className="h-4 w-4 text-blue-500" />}
        value={`${stats.queue_count || 0} Item`}
        note={`Total artikel terbit di WordPress: ${stats.total_articles || 0}`}
      />
    </div>
  );
}
