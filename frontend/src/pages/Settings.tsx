import { useState, useEffect } from 'react';
import { Settings as SettingsIcon } from 'lucide-react';
import { apiFetch } from '../lib/api';
import { toast } from 'sonner';
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

export default function Settings() {
  const [config, setConfig] = useState<any>({});
  const [profile, setProfile] = useState({ name: '', email: '', password: '' });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    Promise.all([
      apiFetch('/api/settings').then(res => res.json()),
      apiFetch('/api/profile').then(res => res.json())
    ]).then(([settingsData, profileData]) => {
      setConfig(settingsData.config || {});
      if (profileData.success) {
        setProfile({ name: profileData.profile.name || '', email: profileData.profile.email || '', password: '' });
      }
      setLoading(false);
    });
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setMessage('');

    const formData = new FormData();
    Object.keys(config).forEach(key => {
      if (typeof config[key] === 'boolean') {
        if (config[key]) formData.append(key, 'on');
      } else if (config[key] !== null && config[key] !== undefined && typeof config[key] !== 'object') {
        formData.append(key, config[key].toString());
      }
    });

    try {
      const res = await apiFetch('/save-config', {
        method: 'POST',
        body: formData,
      });
      if (res.ok) {
        toast.success('Settings saved successfully!');
      } else {
        toast.error('Failed to save settings.');
      }
    } catch (err) {
      toast.error('Network error.');
    } finally {
      setSaving(false);
    }
  };



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

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value, type } = e.target;
    const checked = (e.target as HTMLInputElement).checked;
    setConfig((prev: any) => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value
    }));
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
        <p className="text-muted-foreground">Manage your API keys, integrations, and scheduling preferences.</p>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
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

        {/* System Settings */}
        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Gemini AI */}
          <Card className="border-border/50 shadow-md">
            <CardHeader>
              <CardTitle>Gemini AI</CardTitle>
              <CardDescription>Configure Google Gemini API for content generation.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 pb-8">
              <div className="space-y-2">
                <Label htmlFor="gemini_api_key">API Key</Label>
                <Input 
                  id="gemini_api_key" 
                  name="gemini_api_key" 
                  type="password"
                  value={config.gemini_api_key || ''} 
                  onChange={handleChange} 
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="gemini_model">Text Model</Label>
                <select 
                  id="gemini_model" 
                  name="gemini_model" 
                  value={config.gemini_model || 'gemini-3.5-flash'} 
                  onChange={handleChange}
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
                  name="gemini_image_model" 
                  value={config.gemini_image_model || 'gemini-3.1-flash-image'} 
                  onChange={handleChange}
                  className="flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <option value="gemini-3.1-flash-image">Gemini 3.1 Flash Image (Recommended)</option>
                  <option value="gemini-3-pro-image">Gemini 3 Pro Image</option>
                  <option value="gemini-3.1-flash-image-preview">Gemini 3.1 Flash Image Preview (Legacy)</option>
                </select>
              </div>
            </CardContent>

            <CardFooter className="flex justify-between items-center border-t bg-muted/50 p-6">
              {message && (
                <p className={`text-sm ${message.includes('success') ? 'text-green-600' : 'text-red-600'}`}>
                  {message}
                </p>
              )}
              <div className="flex justify-end w-full">
                <Button 
                  type="submit" 
                  disabled={saving} 
                  className="w-full sm:w-auto min-w-[200px] bg-gradient-to-r from-primary to-indigo-600 hover:from-primary/90 hover:to-indigo-600/90 text-white shadow-md text-base py-6"
                >
                  {saving ? 'Saving...' : 'Save Configuration'}
                </Button>
              </div>
            </CardFooter>
          </Card>
      </form>
      </div>
    </div>
  );
}
