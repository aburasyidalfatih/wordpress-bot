import { useState, useEffect } from 'react';
import { Settings as SettingsIcon } from 'lucide-react';
import { apiFetch } from '../lib/api';
import { toast } from 'sonner';
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

export default function Settings() {
  const [profile, setProfile] = useState({ name: '', email: '', password: '', role: 'user' });
  const [loading, setLoading] = useState(true);
  const [savingProfile, setSavingProfile] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    apiFetch('/api/profile', { signal: controller.signal })
      .then(res => res.json())
      .then(profileData => {
        if (profileData.success) {
          setProfile({ 
            name: profileData.profile.name || '', 
            email: profileData.profile.email || '', 
            password: '',
            role: profileData.profile.role || 'user'
          });
        }
        setLoading(false);
      })
      .catch(err => {
        if (err.name !== 'AbortError') {
          console.error('Failed to load profile:', err);
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, []);

  const handleProfileSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingProfile(true);
    try {
      const res = await apiFetch('/api/profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(profile)
      });
      const data = await res.json();
      if (data.success) {
        toast.success(data.message || 'Profile updated successfully!');
        setProfile(prev => ({ ...prev, password: '' })); // clear password field
      } else {
        toast.error(data.error || 'Failed to update profile.');
      }
    } catch (err) {
      toast.error('Network error.');
    } finally {
      setSavingProfile(false);
    }
  };

  const handleProfileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setProfile(prev => ({ ...prev, [name]: value }));
  };

  if (loading) return <div className="p-8">Loading settings...</div>;

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-primary to-indigo-600 dark:from-primary dark:to-indigo-400 bg-clip-text text-transparent flex items-center gap-2">
          <SettingsIcon className="h-8 w-8 text-primary" /> Settings
        </h1>
        <p className="text-muted-foreground">Manage your personal profile information and account password.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8 items-start">
        {/* Profile Settings */}
        <form onSubmit={handleProfileSubmit}>
          <Card className="border-border/50 shadow-md h-full">
            <CardHeader>
              <CardTitle>Profile Settings</CardTitle>
              <CardDescription>Update your personal information and password.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 pb-8">
              <div className="space-y-2">
                <Label htmlFor="name">Full Name</Label>
                <Input 
                  id="name" 
                  name="name" 
                  value={profile.name} 
                  onChange={handleProfileChange} 
                  placeholder="John Doe"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="email">Email Address</Label>
                <Input 
                  id="email" 
                  name="email" 
                  type="email"
                  value={profile.email} 
                  onChange={handleProfileChange} 
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="password">New Password</Label>
                <Input 
                  id="password" 
                  name="password" 
                  type="password"
                  value={profile.password} 
                  onChange={handleProfileChange} 
                  placeholder="Leave blank to keep unchanged"
                />
              </div>
            </CardContent>
            <CardFooter className="bg-muted/50 py-4 mt-auto">
              <Button type="submit" disabled={savingProfile} className="w-full">
                {savingProfile ? 'Saving...' : 'Update Profile'}
              </Button>
            </CardFooter>
          </Card>
        </form>

        {/* Admin SEO Tools */}
        {profile.role === 'admin' && (
          <BulkUpdateYear />
        )}
      </div>
    </div>
  );
}

function BulkUpdateYear() {
  return <BulkUpdateYearComponent />;
}

function BulkUpdateYearComponent() {
  const [siteId, setSiteId] = useState('');
  const [fromYear, setFromYear] = useState('2026');
  const [toYear, setToYear] = useState('2027');
  const [loading, setLoading] = useState(false);
  const [sites, setSites] = useState<any[]>([]);

  useEffect(() => {
    apiFetch('/api/sites')
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          setSites(data.sites || []);
          if (data.sites && data.sites.length > 0) {
            setSiteId(data.sites[0].id.toString());
          }
        }
      });
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!siteId || !fromYear || !toYear) {
      toast.error('All fields are required');
      return;
    }
    setLoading(true);
    try {
      const res = await apiFetch('/api/admin/bulk_update_year', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ site_id: parseInt(siteId), from_year: fromYear, to_year: toYear })
      });
      const data = await res.json();
      if (data.success) {
        toast.success(data.message || 'Bulk update started in background');
      } else {
        toast.error(data.error || 'Failed to start bulk update');
      }
    } catch (err) {
      toast.error('Network error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <Card className="border-border/50 shadow-md h-full">
        <CardHeader>
          <CardTitle>Bulk Update SEO Year (Admin)</CardTitle>
          <CardDescription>Update all articles containing a specific year in their title and content to a new year.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 pb-8">
          <div className="space-y-2">
            <Label>Select Site</Label>
            <select
              value={siteId}
              onChange={(e) => setSiteId(e.target.value)}
              className="flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <option value="" disabled>Select a site</option>
              {sites.map(site => (
                <option key={site.id} value={site.id.toString()}>{site.site_name}</option>
              ))}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>From Year</Label>
              <Input value={fromYear} onChange={e => setFromYear(e.target.value)} placeholder="e.g. 2026" />
            </div>
            <div className="space-y-2">
              <Label>To Year</Label>
              <Input value={toYear} onChange={e => setToYear(e.target.value)} placeholder="e.g. 2027" />
            </div>
          </div>
        </CardContent>
        <CardFooter className="bg-muted/50 py-4 mt-auto">
          <Button type="submit" disabled={loading} className="w-full">
            {loading ? 'Starting...' : 'Start Bulk Update'}
          </Button>
        </CardFooter>
      </Card>
    </form>
  );
}
