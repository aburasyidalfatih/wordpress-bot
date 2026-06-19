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
    apiFetch('/api/profile')
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
      });
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

      <div className="max-w-xl">
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
      </div>
    </div>
  );
}
