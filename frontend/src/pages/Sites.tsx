import { useState } from 'react';
import { Bot, Plus, Trash2, Edit, RefreshCw, ChevronRight } from 'lucide-react';
import { apiFetch } from '../lib/api';
import { toast } from 'sonner';
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useSiteContext } from '@/contexts/SiteContext';
import type { WordPressSite } from '@/contexts/SiteContext';

export default function Sites() {
  const { sites, fetchSites, setSelectedSiteId, selectedSiteId } = useSiteContext();
  const [isEditing, setIsEditing] = useState(false);
  const [currentSite, setCurrentSite] = useState<Partial<WordPressSite>>({});
  const [saving, setSaving] = useState(false);
  const [activeTab, setActiveTab] = useState('wordpress');

  const handleEdit = (site: WordPressSite) => {
    setCurrentSite(site);
    setIsEditing(true);
    setActiveTab('wordpress');
  };

  const handleCreateNew = () => {
    setCurrentSite({
      site_name: '',
      wordpress_url: '',
      wordpress_username: '',
      wordpress_password: '',
      is_active: true,
      auto_post: false,
      schedule_hours: '0,6,12,18',
      timezone: 'Asia/Jakarta',
      language: 'id',
      telegram_enabled: false,
      facebook_enabled: false,
      twitter_enabled: false,
      threads_enabled: false,
    });
    setIsEditing(true);
    setActiveTab('wordpress');
  };

  const handleCancel = () => {
    setIsEditing(false);
    setCurrentSite({});
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value, type, checked } = e.target;
    setCurrentSite(prev => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value
    }));
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);

    try {
      const url = currentSite.id ? `/api/sites/${currentSite.id}` : '/api/sites';
      const method = currentSite.id ? 'PUT' : 'POST';

      const res = await apiFetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(currentSite)
      });
      
      const data = await res.json();
      
      if (res.ok && data.success) {
        toast.success(`Website ${currentSite.id ? 'updated' : 'created'} successfully!`);
        await fetchSites();
        if (!currentSite.id && data.site_id) {
            setSelectedSiteId(data.site_id);
        }
        setIsEditing(false);
      } else {
        toast.error(data.error || 'Failed to save website.');
      }
    } catch (err) {
      toast.error('Network error.');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('Are you sure you want to delete this website? This cannot be undone.')) return;
    try {
      const res = await apiFetch(`/api/sites/${id}`, { method: 'DELETE' });
      if (res.ok) {
        toast.success('Website deleted successfully.');
        await fetchSites();
        if (selectedSiteId === id) {
            setSelectedSiteId(null);
        }
      } else {
        const data = await res.json();
        toast.error(data.error || 'Failed to delete website.');
      }
    } catch (err) {
      toast.error('Network error.');
    }
  };

  const handleFetchCategories = async () => {
    if (!currentSite.id) {
        toast.error('Please save the website first before fetching categories.');
        return;
    }
    toast.info('Fetching categories...');
    try {
      const res = await apiFetch(`/api/sites/${currentSite.id}/fetch-categories`, { method: 'POST' });
      const data = await res.json();
      if (res.ok && data.success) {
        setCurrentSite(prev => {
          const newCategories = data.categories || [];
          const existingSelected = (prev.selected_categories || []).filter((sel: any) =>
            newCategories.some((cat: any) => cat.id === sel.id)
          );
          const finalSelection = existingSelected.length === 0 ? newCategories : existingSelected;
          return {
            ...prev,
            categories: newCategories,
            selected_categories: finalSelection
          };
        });
        toast.success('Categories fetched successfully!');
        fetchSites(); // refresh global state
      } else {
        toast.error(data.error || 'Failed to fetch categories.');
      }
    } catch (err) {
      toast.error('Network error fetching categories.');
    }
  };

  if (isEditing) {
    return (
      <div className="space-y-6 animate-in fade-in zoom-in-95 duration-300">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-primary to-indigo-600 bg-clip-text text-transparent">
              {currentSite.id ? 'Edit Website' : 'New Website'}
            </h1>
            <p className="text-muted-foreground mt-1">Configure your WordPress integration and automation rules.</p>
          </div>
          <Button variant="outline" onClick={handleCancel}>Cancel</Button>
        </div>

        <div className="flex flex-col md:flex-row gap-6">
          {/* Vertical Tabs */}
          <div className="w-full md:w-64 space-y-1">
            {['wordpress', 'automation', 'telegram', 'facebook', 'twitter', 'threads'].map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`w-full flex items-center justify-between px-4 py-3 rounded-xl text-sm font-medium transition-all ${
                  activeTab === tab 
                    ? 'bg-primary text-primary-foreground shadow-md scale-[1.02]' 
                    : 'text-muted-foreground hover:bg-secondary hover:text-foreground'
                }`}
              >
                <span className="capitalize">{tab}</span>
                {activeTab === tab && <ChevronRight className="h-4 w-4" />}
              </button>
            ))}
          </div>

          {/* Form Content */}
          <div className="flex-1">
            <Card className="border-border/50 shadow-xl bg-card/80 backdrop-blur-sm">
              <form onSubmit={handleSave}>
                <CardHeader className="pb-6 border-b mb-6">
                  <CardTitle className="capitalize text-xl">{activeTab} Configuration</CardTitle>
                </CardHeader>
                <CardContent className="space-y-6 min-h-[400px] pb-8">
                  
                  {activeTab === 'wordpress' && (
                    <div className="space-y-4 animate-in fade-in slide-in-from-right-4 duration-300">
                      <div className="space-y-2">
                        <Label htmlFor="site_name">Website Name <span className="text-red-500">*</span></Label>
                        <Input id="site_name" name="site_name" required value={currentSite.site_name || ''} onChange={handleChange} placeholder="My Awesome Blog" />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="wordpress_url">WordPress URL <span className="text-red-500">*</span></Label>
                        <Input id="wordpress_url" name="wordpress_url" required value={currentSite.wordpress_url || ''} onChange={handleChange} placeholder="https://myblog.com" />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="wordpress_username">WP Username <span className="text-red-500">*</span></Label>
                        <Input id="wordpress_username" name="wordpress_username" required value={currentSite.wordpress_username || ''} onChange={handleChange} />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="wordpress_password">Application Password {!currentSite.id && <span className="text-red-500">*</span>}</Label>
                        <Input id="wordpress_password" name="wordpress_password" required={!currentSite.id} type="password" value={currentSite.wordpress_password || ''} onChange={handleChange} placeholder={currentSite.id ? (currentSite.has_wordpress_password ? "Sudah tersimpan. Isi untuk mengganti." : "Belum tersimpan.") : ""} />
                        <p className="text-xs text-muted-foreground">Use WordPress Application Passwords, not your main login password.</p>
                      </div>

                      {currentSite.id && (
                        <div className="pt-4 border-t space-y-4">
                          <div className="flex justify-between items-center">
                            <div className="flex items-center gap-3">
                              <h3 className="font-medium">Categories</h3>
                              {currentSite.categories && currentSite.categories.length > 0 && (
                                <div className="flex items-center gap-2 border-l pl-3 ml-1">
                                  <Button 
                                    type="button" 
                                    variant="link" 
                                    size="xs"
                                    className="p-0 text-xs font-bold text-primary hover:no-underline"
                                    onClick={() => {
                                      setCurrentSite({
                                        ...currentSite,
                                        selected_categories: [...(currentSite.categories || [])]
                                      });
                                    }}
                                  >
                                    Centang Semua
                                  </Button>
                                  <span className="text-muted-foreground/30 text-[10px]">|</span>
                                  <Button 
                                    type="button" 
                                    variant="link" 
                                    size="xs"
                                    className="p-0 text-xs font-bold text-muted-foreground hover:no-underline"
                                    onClick={() => {
                                      setCurrentSite({
                                        ...currentSite,
                                        selected_categories: []
                                      });
                                    }}
                                  >
                                    Hapus Semua
                                  </Button>
                                </div>
                              )}
                            </div>
                            <Button type="button" variant="outline" size="sm" onClick={handleFetchCategories}>
                              <RefreshCw className="h-4 w-4 mr-2" /> Fetch Categories
                            </Button>
                          </div>

                          {currentSite.categories && currentSite.categories.length > 0 ? (
                            <div className="space-y-2 max-h-48 overflow-y-auto p-3 border rounded-xl bg-muted/30">
                              <div className="flex items-center space-x-3 p-1 border-b pb-2 mb-2">
                                <input
                                  type="checkbox"
                                  id="select_all_categories_checkbox"
                                  checked={
                                    currentSite.categories.length > 0 &&
                                    (currentSite.selected_categories || []).length === currentSite.categories.length
                                  }
                                  onChange={(e) => {
                                    if (e.target.checked) {
                                      setCurrentSite({
                                        ...currentSite,
                                        selected_categories: [...(currentSite.categories || [])]
                                      });
                                    } else {
                                      setCurrentSite({
                                        ...currentSite,
                                        selected_categories: []
                                      });
                                    }
                                  }}
                                  className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary cursor-pointer"
                                />
                                <Label htmlFor="select_all_categories_checkbox" className="font-bold text-primary cursor-pointer text-xs uppercase tracking-wider">
                                  Centang Semua
                                </Label>
                              </div>
                              {currentSite.categories.map((cat: any) => (
                                <div key={cat.id} className="flex items-center space-x-3 p-1">
                                  <input
                                    type="checkbox"
                                    id={`cat_${cat.id}`}
                                    name="selected_categories"
                                    value={cat.id}
                                    checked={currentSite.selected_categories?.some((c: any) => c.id === cat.id) || false}
                                    onChange={(e) => {
                                      const newSelection = e.target.checked
                                        ? [...(currentSite.selected_categories || []), cat]
                                        : (currentSite.selected_categories || []).filter((c: any) => c.id !== cat.id);
                                      setCurrentSite({ ...currentSite, selected_categories: newSelection });
                                    }}
                                    className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
                                  />
                                  <Label htmlFor={`cat_${cat.id}`} className="font-medium cursor-pointer">
                                    {cat.name} <span className="text-xs text-muted-foreground ml-1">({cat.count !== undefined && cat.count !== null ? cat.count : 0} posts)</span>
                                  </Label>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <p className="text-sm text-muted-foreground">No categories fetched yet. Save the website and click Fetch Categories.</p>
                          )}
                        </div>
                      )}
                    </div>
                  )}

                  {activeTab === 'automation' && (
                    <div className="space-y-4 animate-in fade-in slide-in-from-right-4 duration-300">
                      
                      <div className="flex items-center justify-between p-4 border rounded-xl bg-muted/20">
                        <div className="space-y-0.5">
                          <Label className="text-base font-semibold text-foreground">Website Status</Label>
                          <p className="text-sm text-muted-foreground">Turn this off to completely disable the bot for this website.</p>
                        </div>
                        <button
                          type="button"
                          onClick={() => setCurrentSite({ ...currentSite, is_active: currentSite.is_active !== false ? false : true })}
                          className={`${currentSite.is_active !== false ? 'bg-primary' : 'bg-muted'} relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none`}
                        >
                          <span
                            className={`${currentSite.is_active !== false ? 'translate-x-5' : 'translate-x-0'} pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out`}
                          />
                        </button>
                      </div>
                      
                      <div className="flex items-center justify-between p-4 border rounded-xl bg-muted/20">
                        <div className="space-y-0.5">
                          <Label className="text-base font-semibold text-foreground">Auto Posting (Publishing)</Label>
                          <p className="text-sm text-muted-foreground">Automatically generate and publish posts based on schedule.</p>
                        </div>
                        <button
                          type="button"
                          onClick={() => setCurrentSite({ ...currentSite, auto_post: !currentSite.auto_post })}
                          className={`${currentSite.auto_post ? 'bg-primary' : 'bg-muted'} relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none`}
                        >
                          <span
                            className={`${currentSite.auto_post ? 'translate-x-5' : 'translate-x-0'} pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out`}
                          />
                        </button>
                      </div>


                      
                      <div className="pt-4 border-t grid grid-cols-1 md:grid-cols-3 gap-4">
                        <div className="space-y-2">
                          <Label htmlFor="schedule_hours" className="text-foreground">Posting Schedule (Hours)</Label>
                          <Input id="schedule_hours" name="schedule_hours" value={currentSite.schedule_hours || ''} onChange={handleChange} placeholder="0, 6, 12, 18" className="bg-background" />
                          <p className="text-[11px] text-muted-foreground leading-tight">Comma-separated hours (0-23). Example: 0, 6, 12, 18</p>
                        </div>
                        <div className="space-y-2">
                          <Label htmlFor="timezone" className="text-foreground">Timezone</Label>
                          <select 
                            id="timezone" 
                            name="timezone" 
                            value={currentSite.timezone || 'Asia/Jakarta'} 
                            onChange={(e) => setCurrentSite(prev => ({ ...prev, timezone: e.target.value }))}
                            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            <option value="Asia/Jakarta">Asia/Jakarta (WIB, GMT+7)</option>
                            <option value="Asia/Makassar">Asia/Makassar (WITA, GMT+8)</option>
                            <option value="Asia/Jayapura">Asia/Jayapura (WIT, GMT+9)</option>
                            <option value="Asia/Singapore">Asia/Singapore (GMT+8)</option>
                            <option value="UTC">UTC (GMT+0)</option>
                            <option value="Europe/London">Europe/London (GMT/BST)</option>
                            <option value="Europe/Paris">Europe/Paris (CET/CEST)</option>
                            <option value="America/New_York">America/New_York (EST/EDT)</option>
                            <option value="America/Los_Angeles">America/Los_Angeles (PST/PDT)</option>
                            <option value="Asia/Tokyo">Asia/Tokyo (JST, GMT+9)</option>
                            <option value="Australia/Sydney">Australia/Sydney (AEST/AEDT)</option>
                          </select>
                          <p className="text-[11px] text-muted-foreground leading-tight">Select the timezone for this website's posting schedule.</p>
                        </div>
                        <div className="space-y-2">
                          <Label htmlFor="language" className="text-foreground">Language</Label>
                          <select 
                            id="language" 
                            name="language" 
                            value={currentSite.language || 'id'} 
                            onChange={(e) => setCurrentSite(prev => ({ ...prev, language: e.target.value }))}
                            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            <option value="id">Bahasa Indonesia</option>
                            <option value="en">English (US/UK)</option>
                          </select>
                          <p className="text-[11px] text-muted-foreground leading-tight">Select the language of the generated articles.</p>
                        </div>
                      </div>

                    </div>
                  )}

                  {activeTab === 'telegram' && (
                    <div className="space-y-4 animate-in fade-in slide-in-from-right-4 duration-300">
                      <div className="flex items-center justify-between p-4 border rounded-xl bg-muted/20">
                        <div className="space-y-0.5">
                          <Label className="text-base font-semibold text-foreground">Telegram Integration</Label>
                          <p className="text-sm text-muted-foreground">Post articles automatically to Telegram channel or notify admin chat.</p>
                        </div>
                        <button
                          type="button"
                          onClick={() => setCurrentSite({ ...currentSite, telegram_enabled: !currentSite.telegram_enabled })}
                          className={`${currentSite.telegram_enabled ? 'bg-primary' : 'bg-muted'} relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none`}
                        >
                          <span
                            className={`${currentSite.telegram_enabled ? 'translate-x-5' : 'translate-x-0'} pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out`}
                          />
                        </button>
                      </div>
                      {currentSite.telegram_enabled && (
                        <div className="space-y-4 pt-4 border-t border-border/50">
                          <div className="space-y-2">
                            <Label>Bot Token</Label>
                            <Input name="telegram_bot_token" type="password" value={currentSite.telegram_bot_token || ''} onChange={handleChange} placeholder={currentSite.has_telegram_bot_token ? "Sudah tersimpan. Isi untuk mengganti." : "Bot token"} />
                          </div>
                          <div className="space-y-2">
                            <Label>Admin Chat ID (for notifications)</Label>
                            <Input name="telegram_chat_id" value={currentSite.telegram_chat_id || ''} onChange={handleChange} />
                          </div>
                          <div className="flex items-center justify-between p-4 border rounded-xl bg-muted/10">
                            <div className="space-y-0.5">
                              <Label className="font-semibold text-foreground">Post articles to Telegram Channel</Label>
                              <p className="text-xs text-muted-foreground">Automatically forward newly published blog posts to a Telegram Channel.</p>
                            </div>
                            <button
                              type="button"
                              onClick={() => setCurrentSite({ ...currentSite, telegram_post_to_channel: !currentSite.telegram_post_to_channel })}
                              className={`${currentSite.telegram_post_to_channel ? 'bg-primary' : 'bg-muted'} relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none`}
                            >
                              <span
                                className={`${currentSite.telegram_post_to_channel ? 'translate-x-5' : 'translate-x-0'} pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out`}
                              />
                            </button>
                          </div>
                          {currentSite.telegram_post_to_channel && (
                            <div className="space-y-2 pl-6">
                              <Label>Channel ID (e.g. @mychannel)</Label>
                              <Input name="telegram_channel_id" value={currentSite.telegram_channel_id || ''} onChange={handleChange} />
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}

                  {activeTab === 'facebook' && (
                    <div className="space-y-4 animate-in fade-in slide-in-from-right-4 duration-300">
                      <div className="flex items-center justify-between p-4 border rounded-xl bg-muted/20">
                        <div className="space-y-0.5">
                          <Label className="text-base font-semibold text-foreground">Facebook Page Posting</Label>
                          <p className="text-sm text-muted-foreground">Automatically post new articles to your Facebook Page feed.</p>
                        </div>
                        <button
                          type="button"
                          onClick={() => setCurrentSite({ ...currentSite, facebook_enabled: !currentSite.facebook_enabled })}
                          className={`${currentSite.facebook_enabled ? 'bg-primary' : 'bg-muted'} relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none`}
                        >
                          <span
                            className={`${currentSite.facebook_enabled ? 'translate-x-5' : 'translate-x-0'} pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out`}
                          />
                        </button>
                      </div>
                      {currentSite.facebook_enabled && (
                        <div className="space-y-4 pt-4 border-t border-border/50">
                          <div className="space-y-2">
                            <Label>Page ID</Label>
                            <Input name="facebook_page_id" value={currentSite.facebook_page_id || ''} onChange={handleChange} />
                          </div>
                          <div className="space-y-2">
                            <Label>Access Token</Label>
                            <Input name="facebook_access_token" type="password" value={currentSite.facebook_access_token || ''} onChange={handleChange} placeholder={currentSite.has_facebook_access_token ? "Sudah tersimpan. Isi untuk mengganti." : "Access token"} />
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {activeTab === 'twitter' && (
                    <div className="space-y-4 animate-in fade-in slide-in-from-right-4 duration-300">
                      <div className="flex items-center justify-between p-4 border rounded-xl bg-muted/20">
                        <div className="space-y-0.5">
                          <Label className="text-base font-semibold text-foreground">Twitter (X) Posting</Label>
                          <p className="text-sm text-muted-foreground">Automatically tweet links to your new articles on X/Twitter.</p>
                        </div>
                        <button
                          type="button"
                          onClick={() => setCurrentSite({ ...currentSite, twitter_enabled: !currentSite.twitter_enabled })}
                          className={`${currentSite.twitter_enabled ? 'bg-primary' : 'bg-muted'} relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none`}
                        >
                          <span
                            className={`${currentSite.twitter_enabled ? 'translate-x-5' : 'translate-x-0'} pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out`}
                          />
                        </button>
                      </div>
                      {currentSite.twitter_enabled && (
                        <div className="space-y-4 pt-4 border-t border-border/50">
                          <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-2">
                              <Label>API Key</Label>
                              <Input name="twitter_api_key" type="password" value={currentSite.twitter_api_key || ''} onChange={handleChange} placeholder={currentSite.has_twitter_api_key ? "Tersimpan" : "API Key"} />
                            </div>
                            <div className="space-y-2">
                              <Label>API Secret</Label>
                              <Input name="twitter_api_secret" type="password" value={currentSite.twitter_api_secret || ''} onChange={handleChange} placeholder={currentSite.has_twitter_api_secret ? "Tersimpan" : "API Secret"} />
                            </div>
                            <div className="space-y-2">
                              <Label>Access Token</Label>
                              <Input name="twitter_access_token" type="password" value={currentSite.twitter_access_token || ''} onChange={handleChange} placeholder={currentSite.has_twitter_access_token ? "Tersimpan" : "Access Token"} />
                            </div>
                            <div className="space-y-2">
                              <Label>Access Secret</Label>
                              <Input name="twitter_access_secret" type="password" value={currentSite.twitter_access_secret || ''} onChange={handleChange} placeholder={currentSite.has_twitter_access_secret ? "Tersimpan" : "Access Secret"} />
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {activeTab === 'threads' && (
                    <div className="space-y-4 animate-in fade-in slide-in-from-right-4 duration-300">
                      <div className="flex items-center justify-between p-4 border rounded-xl bg-muted/20">
                        <div className="space-y-0.5">
                          <Label className="text-base font-semibold text-foreground">Threads Posting</Label>
                          <p className="text-sm text-muted-foreground">Automatically post links to your new articles on Instagram Threads.</p>
                        </div>
                        <button
                          type="button"
                          onClick={() => setCurrentSite({ ...currentSite, threads_enabled: !currentSite.threads_enabled })}
                          className={`${currentSite.threads_enabled ? 'bg-primary' : 'bg-muted'} relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none`}
                        >
                          <span
                            className={`${currentSite.threads_enabled ? 'translate-x-5' : 'translate-x-0'} pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out`}
                          />
                        </button>
                      </div>
                      {currentSite.threads_enabled && (
                        <div className="space-y-4 pt-4 border-t border-border/50">
                          <div className="space-y-2">
                            <Label>User ID</Label>
                            <Input name="threads_user_id" value={currentSite.threads_user_id || ''} onChange={handleChange} />
                          </div>
                          <div className="space-y-2">
                            <Label>Access Token</Label>
                            <Input name="threads_access_token" type="password" value={currentSite.threads_access_token || ''} onChange={handleChange} placeholder={currentSite.has_threads_access_token ? "Sudah tersimpan. Isi untuk mengganti." : "Access token"} />
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                </CardContent>
                <CardFooter className="flex justify-between border-t p-6 bg-muted/10">
                  <div className="flex gap-2">
                    {currentSite.id && (
                      <Button type="button" variant="destructive" onClick={() => handleDelete(currentSite.id!)}>
                        <Trash2 className="h-4 w-4 mr-2" /> Delete Website
                      </Button>
                    )}
                  </div>
                  <div className="flex gap-3">
                    <Button type="button" variant="ghost" onClick={handleCancel}>Cancel</Button>
                    <Button type="submit" disabled={saving} className="bg-gradient-to-r from-primary to-indigo-600 shadow-md hover:opacity-90">
                      {saving ? 'Saving...' : 'Save Configuration'}
                    </Button>
                  </div>
                </CardFooter>
              </form>
            </Card>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-primary to-indigo-600 bg-clip-text text-transparent flex items-center gap-3">
            <Bot className="h-8 w-8 text-primary" /> Websites
          </h1>
          <p className="text-muted-foreground mt-1">Manage your unlimited WordPress sites and integrations.</p>
        </div>
        <Button onClick={handleCreateNew} className="rounded-xl shadow-lg shadow-primary/20 bg-gradient-to-r from-primary to-indigo-600 hover:opacity-90">
          <Plus className="h-5 w-5 mr-2" /> New Website
        </Button>
      </div>

      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {sites.map(site => (
          <Card 
            key={site.id} 
            className={`group relative overflow-hidden transition-all duration-300 hover:shadow-xl hover:-translate-y-1 border-border/50 ${selectedSiteId === site.id ? 'ring-2 ring-primary ring-offset-2 ring-offset-background' : ''}`}
          >
            {/* Background Gradient decoration */}
            <div className="absolute inset-0 bg-gradient-to-br from-primary/5 to-indigo-600/5 opacity-0 group-hover:opacity-100 transition-opacity" />
            
            <CardHeader className="relative z-10 border-b border-border/40 pb-4 mb-2">
              <div className="flex justify-between items-start">
                <div>
                  <CardTitle className="text-xl font-bold">{site.site_name}</CardTitle>
                  <CardDescription className="mt-1.5 text-[13px] truncate max-w-[200px] text-muted-foreground/80" title={site.wordpress_url}>
                    {site.wordpress_url}
                  </CardDescription>
                </div>
                <div className={`px-2.5 py-1 text-xs font-semibold rounded-full border ${site.is_active ? 'bg-green-500/10 text-green-600 border-green-500/20' : 'bg-muted text-muted-foreground'}`}>
                  {site.is_active ? 'Active' : 'Paused'}
                </div>
              </div>
            </CardHeader>
            <CardContent className="relative z-10 space-y-4">
              <div className="flex flex-wrap gap-2">
                {site.telegram_enabled && <span className="bg-blue-500/10 text-blue-600 text-[10px] px-2 py-0.5 rounded-md font-semibold border border-blue-500/20">Telegram</span>}
                {site.facebook_enabled && <span className="bg-blue-600/10 text-blue-700 text-[10px] px-2 py-0.5 rounded-md font-semibold border border-blue-600/20">Facebook</span>}
                {site.twitter_enabled && <span className="bg-slate-800/10 dark:bg-slate-200/10 text-slate-900 dark:text-slate-100 text-[10px] px-2 py-0.5 rounded-md font-semibold border border-slate-500/20">X</span>}
                {site.threads_enabled && <span className="bg-purple-500/10 text-purple-600 text-[10px] px-2 py-0.5 rounded-md font-semibold border border-purple-500/20">Threads</span>}
              </div>
              <div className="flex items-center justify-between text-sm text-muted-foreground border-t pt-4">
                <span>Categories</span>
                <span className="font-medium text-foreground bg-secondary px-2 py-0.5 rounded-md">
                  {site.selected_categories?.length || 0} / {site.categories?.length || 0}
                </span>
              </div>
            </CardContent>
            <CardFooter className="relative z-10 flex gap-2 px-6 pb-6 pt-4 border-t bg-muted/30">
              <Button 
                variant="outline" 
                size="sm" 
                className="w-full bg-background/50 backdrop-blur-sm group-hover:bg-primary group-hover:text-primary-foreground group-hover:border-primary transition-all duration-300"
                onClick={() => handleEdit(site)}
              >
                <Edit className="h-4 w-4 mr-2" /> Configure
              </Button>
              {selectedSiteId !== site.id && (
                 <Button 
                   variant="ghost" 
                   size="sm" 
                   className="shrink-0"
                   onClick={() => {
                     setSelectedSiteId(site.id);
                     toast.success(`Switched to website ${site.site_name}`);
                   }}
                 >
                   Select
                 </Button>
              )}
            </CardFooter>
          </Card>
        ))}

        {sites.length === 0 && (
          <div className="col-span-full py-20 text-center border-2 border-dashed rounded-2xl bg-muted/20">
            <Bot className="h-16 w-16 mx-auto text-muted-foreground opacity-50 mb-4" />
            <h3 className="text-xl font-bold text-foreground">No Websites Yet</h3>
            <p className="text-muted-foreground mt-2 mb-6 max-w-sm mx-auto">Create your first WordPress integration to start generating and scheduling articles.</p>
            <Button onClick={handleCreateNew} className="rounded-xl shadow-lg bg-gradient-to-r from-primary to-indigo-600 hover:opacity-90">
              <Plus className="h-5 w-5 mr-2" /> Create First Website
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
