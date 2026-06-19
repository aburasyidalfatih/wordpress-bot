import { useState, useEffect } from 'react';
import { apiFetch } from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Activity, HardDrive, Cpu, MemoryStick, Clock, Download } from 'lucide-react';
import { buttonVariants } from '@/components/ui/button';

export default function Monitor() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const fetchMonitor = () => {
    apiFetch('/api/monitor')
      .then(res => res.json())
      .then(d => {
        setData(d);
        setLoading(false);
      });
  };

  useEffect(() => {
    fetchMonitor();
    const interval = setInterval(fetchMonitor, 5000); // Auto refresh every 5s
    return () => clearInterval(interval);
  }, []);

  if (loading && !data) return <div className="p-8">Loading monitoring data...</div>;

  const { system_info, service_info, recent_errors } = data || {};

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-primary to-indigo-600 dark:from-primary dark:to-indigo-400 bg-clip-text text-transparent flex items-center gap-2">
          <Activity className="h-8 w-8 text-primary" /> System Monitor
        </h1>
        <p className="text-muted-foreground">Real-time health and performance metrics of your AutoWP worker.</p>
      </div>

      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">CPU Usage</CardTitle>
            <Cpu className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{system_info?.cpu_percent}%</div>
            <div className="w-full bg-secondary h-2 mt-2 rounded-full overflow-hidden">
              <div className="bg-primary h-full transition-all" style={{ width: `${system_info?.cpu_percent}%` }} />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Memory Usage</CardTitle>
            <MemoryStick className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{system_info?.memory_percent}%</div>
            <div className="w-full bg-secondary h-2 mt-2 rounded-full overflow-hidden">
              <div className="bg-primary h-full transition-all" style={{ width: `${system_info?.memory_percent}%` }} />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Disk Usage</CardTitle>
            <HardDrive className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{system_info?.disk_percent}%</div>
            <div className="w-full bg-secondary h-2 mt-2 rounded-full overflow-hidden">
              <div className="bg-primary h-full transition-all" style={{ width: `${system_info?.disk_percent}%` }} />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Uptime</CardTitle>
            <Clock className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-sm truncate">{system_info?.uptime}</div>
            <p className="text-xs text-muted-foreground mt-2">Server running time</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Activity className="h-5 w-5"/> Background Services</CardTitle>
            <CardDescription>Status of automation scheduler and background workers.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex justify-between items-center py-2 border-b">
              <span className="text-muted-foreground">Scheduler Status</span>
              <span className={`px-2 py-1 rounded-md text-xs font-medium ${service_info?.scheduler_running ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                {service_info?.scheduler_running ? 'Running' : 'Stopped'}
              </span>
            </div>
            <div className="flex justify-between items-center py-2 border-b">
              <span className="text-muted-foreground">Active Jobs</span>
              <span className="font-medium">{service_info?.scheduler_jobs} jobs pending</span>
            </div>
            <div className="flex justify-between items-center py-2 border-b">
              <span className="text-muted-foreground">Log File Size</span>
              <span className="font-medium">{service_info?.log_size ? service_info.log_size.toFixed(2) : '0.00'} MB</span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-start justify-between">
            <div>
              <CardTitle>Recent System Errors</CardTitle>
              <CardDescription>Latest ERROR lines from the application log.</CardDescription>
            </div>
            <a href="http://localhost:5003/download-logs" target="_blank" rel="noreferrer" className={buttonVariants({ variant: 'outline', size: 'sm', className: 'flex items-center gap-2' })}>
              <Download className="h-4 w-4" /> Download Logs
            </a>
          </CardHeader>
          <CardContent>
            <div className="bg-muted/30 p-4 rounded-md font-mono text-xs overflow-x-auto max-h-[250px] overflow-y-auto space-y-2">
              {recent_errors && recent_errors.length > 0 ? (
                recent_errors.map((err: string, i: number) => (
                  <div key={i} className="text-red-500 whitespace-pre-wrap border-b border-red-500/10 pb-2">{err}</div>
                ))
              ) : (
                <div className="text-green-600 font-medium text-center py-8">No recent errors detected. System is healthy!</div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
