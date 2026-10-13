import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

export function SystemLogsCard({ logs }: { logs: string[] }) {
  return (
    <Card className="border-border/50 shadow-md">
      <CardHeader>
        <CardTitle>Konsol Log Sistem</CardTitle>
        <CardDescription>Baris terakhir dari log proses daemon `bot.log`.</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="h-96 w-full rounded-lg bg-black text-green-400 font-mono text-xs overflow-y-auto p-4 border shadow-inner">
          {logs.map((line, idx) => (
            <div key={idx} className="whitespace-pre-wrap leading-relaxed py-0.5 border-b border-green-950/20 hover:bg-green-950/15">
              {line}
            </div>
          ))}
          {logs.length === 0 && <div className="text-muted-foreground text-center pt-10">Belum ada entri log.</div>}
        </div>
      </CardContent>
    </Card>
  );
}
