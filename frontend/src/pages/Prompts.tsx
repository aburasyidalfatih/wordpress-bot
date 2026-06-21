import { useState, useEffect } from 'react';
import { Sparkles, FileText } from 'lucide-react';
import { apiFetch } from '../lib/api';
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { useSiteContext } from '@/contexts/SiteContext';
import EmptyState from '@/components/EmptyState';

export default function Prompts() {
  const { selectedSiteId } = useSiteContext();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  const [articlePrompt, setArticlePrompt] = useState('');
  const [imagePrompt, setImagePrompt] = useState('');
  const [optimizing, setOptimizing] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedSiteId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    apiFetch(`/api/prompts?site_id=${selectedSiteId}`)
      .then(res => res.json())
      .then(d => {
        setData(d);
        setArticlePrompt(d.config?.article_prompt || d.default_article_prompt || '');
        setImagePrompt(d.config?.image_prompt || d.default_image_prompt || '');
        setLoading(false);
      });
  }, [selectedSiteId]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setMessage('');

    const formData = new FormData();
    if (selectedSiteId) {
      formData.append('site_id', selectedSiteId.toString());
    }
    formData.append('article_prompt', articlePrompt);
    formData.append('image_prompt', imagePrompt);

    try {
      const res = await apiFetch('/save-prompts', {
        method: 'POST',
        headers: {
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: formData,
      });
      const result = await res.json();
      if (result.success) {
        setMessage('Prompts saved successfully!');
      } else {
        setMessage('Failed to save prompts.');
      }
    } catch (err) {
      setMessage('Network error.');
    } finally {
      setSaving(false);
    }
  };

  const insertVariable = (setter: any, variable: string) => {
    setter((prev: string) => prev + ` {${variable}}`);
  };

  const handleOptimizePrompt = async (type: 'article' | 'image') => {
    if (!selectedSiteId) return;
    setOptimizing(type);
    setMessage('');
    
    const currentPrompt = type === 'article' ? (articlePrompt || data?.default_article_prompt) : (imagePrompt || data?.default_image_prompt);
    
    try {
      const res = await apiFetch('/api/optimize-prompt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          site_id: selectedSiteId,
          prompt_type: type,
          current_prompt: currentPrompt
        })
      });
      if (!res.ok) {
        const errText = await res.text();
        setMessage(`Server error (${res.status}): ${errText.substring(0, 150)}`);
        setOptimizing(null);
        return;
      }
      const result = await res.json();
      if (result.success) {
        if (type === 'article') {
          setArticlePrompt(result.optimized_prompt);
        } else {
          setImagePrompt(result.optimized_prompt);
        }
        setMessage('Prompt berhasil disesuaikan dengan niche Anda oleh AI!');
      } else {
        setMessage('Gagal mengoptimasi prompt: ' + result.error);
      }
    } catch (err: any) {
      setMessage(`Network error saat optimasi prompt: ${err.message}`);
    } finally {
      setOptimizing(null);
    }
  };

  if (!selectedSiteId) return <EmptyState title="Pengaturan Prompt AI" description="Pilih salah satu website Anda dari menu dropdown di kanan atas untuk menyesuaikan instruksi penulisan artikel dan gambar AI." />;
  if (loading) return <div className="p-8">Loading prompts...</div>;

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-primary to-indigo-600 dark:from-primary dark:to-indigo-400 bg-clip-text text-transparent flex items-center gap-2">
          <FileText className="h-8 w-8 text-primary" /> Content Planner & Prompts
        </h1>
        <p className="text-muted-foreground">Configure the prompts used to generate AI articles and images.</p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        <Card className="border-border/50 shadow-md">
          <CardHeader>
            <div className="flex justify-between items-start">
              <div>
                <CardTitle>Article Generation Prompt</CardTitle>
                <CardDescription>
                  Custom instructions for Gemini AI when generating articles. Available variables: <br/>
                  <div className="mt-2 flex gap-2 flex-wrap">
                    <Button type="button" variant="outline" size="sm" onClick={() => insertVariable(setArticlePrompt, 'topic')}>&#123;topic&#125;</Button>
                    <Button type="button" variant="outline" size="sm" onClick={() => insertVariable(setArticlePrompt, 'existing_titles')}>&#123;existing_titles&#125;</Button>
                    <Button type="button" variant="outline" size="sm" onClick={() => insertVariable(setArticlePrompt, 'research_note')}>&#123;research_note&#125;</Button>
                    <Button type="button" variant="outline" size="sm" onClick={() => insertVariable(setArticlePrompt, 'seo_section')}>&#123;seo_section&#125;</Button>
                  </div>
                </CardDescription>
              </div>
              <Button type="button" variant="outline" onClick={() => handleOptimizePrompt('article')} disabled={optimizing !== null} className="gap-2 border-indigo-200 text-indigo-600 hover:bg-indigo-50 shrink-0">
                <Sparkles className={`h-4 w-4 ${optimizing === 'article' ? 'animate-pulse' : ''}`} />
                {optimizing === 'article' ? 'Menyesuaikan...' : 'Sesuaikan dengan Niche (AI)'}
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <Label htmlFor="article_prompt">Prompt Template</Label>
              <textarea
                id="article_prompt"
                value={articlePrompt}
                onChange={(e) => setArticlePrompt(e.target.value)}
                placeholder={data?.default_article_prompt}
                className="min-h-[300px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              />
              <p className="text-xs text-muted-foreground">Leave empty to use the system default prompt.</p>
            </div>
          </CardContent>
        </Card>

        <Card className="border-border/50 shadow-md">
          <CardHeader>
            <div className="flex justify-between items-start">
              <div>
                <CardTitle>Featured Image Prompt</CardTitle>
                <CardDescription>
                  Instructions for image generation. Available variable: <br/>
                  <div className="mt-2">
                    <Button type="button" variant="outline" size="sm" onClick={() => insertVariable(setImagePrompt, 'topic')}>&#123;topic&#125;</Button>
                  </div>
                </CardDescription>
              </div>
              <Button type="button" variant="outline" onClick={() => handleOptimizePrompt('image')} disabled={optimizing !== null} className="gap-2 border-indigo-200 text-indigo-600 hover:bg-indigo-50 shrink-0">
                <Sparkles className={`h-4 w-4 ${optimizing === 'image' ? 'animate-pulse' : ''}`} />
                {optimizing === 'image' ? 'Menyesuaikan...' : 'Sesuaikan dengan Niche (AI)'}
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <Label htmlFor="image_prompt">Image Prompt Template</Label>
              <textarea
                id="image_prompt"
                value={imagePrompt}
                onChange={(e) => setImagePrompt(e.target.value)}
                placeholder={data?.default_image_prompt}
                className="min-h-[100px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              />
              <p className="text-xs text-muted-foreground">Leave empty to use the system default image prompt.</p>
            </div>
          </CardContent>
          <CardFooter className="flex flex-col items-start gap-4 border-t bg-muted/50 p-6">
            {message && (
              <p className={`text-sm ${message.includes('success') ? 'text-green-600' : 'text-red-600'}`}>
                {message}
              </p>
            )}
            <div className="flex justify-end pt-4 border-t border-border/50 w-full">
              <Button type="submit" disabled={saving} className="w-full sm:w-auto min-w-[200px] bg-gradient-to-r from-primary to-indigo-600 hover:from-primary/90 hover:to-indigo-600/90 text-white shadow-md text-base py-6">
                {saving ? 'Saving...' : 'Save Prompts'}
              </Button>
            </div>
          </CardFooter>
        </Card>
      </form>
    </div>
  );
}
