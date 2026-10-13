import { useState } from 'react';
import type { ReactNode } from 'react';
import { Sparkles, FileText } from 'lucide-react';
import { toast } from 'sonner';
import { apiFetch, NETWORK_ERROR } from '@/lib/api';
import { useSiteContext } from '@/hooks/useSiteContext';
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import type { PromptsData } from '@/lib/types';

type PromptType = 'article' | 'image';

interface StatusMessage {
  text: string;
  tone: 'success' | 'error';
}

interface PromptCardProps {
  id: string;
  title: string;
  description: string;
  variables: string[];
  label: string;
  helper: string;
  textareaClass: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  optimizing: boolean;
  optimizeDisabled: boolean;
  onOptimize: () => void;
  footer?: ReactNode;
}

function PromptCard(props: PromptCardProps) {
  const { id, title, description, variables, label, helper, textareaClass, value, onChange, placeholder, optimizing, optimizeDisabled, onOptimize, footer } = props;
  return (
    <Card className="border-border/50 shadow-md">
      <CardHeader>
        <div className="flex justify-between items-start">
          <div>
            <CardTitle>{title}</CardTitle>
            <CardDescription>
              {description} <br/>
              <div className={variables.length > 1 ? 'mt-2 flex gap-2 flex-wrap' : 'mt-2'}>
                {variables.map(variable => (
                  <Button key={variable} type="button" variant="outline" size="sm" onClick={() => onChange(`${value} {${variable}}`)}>
                    {`{${variable}}`}
                  </Button>
                ))}
              </div>
            </CardDescription>
          </div>
          <Button type="button" variant="outline" onClick={onOptimize} disabled={optimizeDisabled} className="gap-2 border-indigo-200 text-indigo-600 hover:bg-indigo-50 shrink-0">
            <Sparkles className={`h-4 w-4 ${optimizing ? 'animate-pulse' : ''}`} />
            {optimizing ? 'Menyesuaikan...' : 'Sesuaikan dengan Niche (AI)'}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          <Label htmlFor={id}>{label}</Label>
          <textarea
            id={id}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder}
            className={`${textareaClass} w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50`}
          />
          <p className="text-xs text-muted-foreground">{helper}</p>
        </div>
      </CardContent>
      {footer}
    </Card>
  );
}

interface PromptsFormProps {
  siteId: number;
  /** null when loading the prompts failed. */
  data: PromptsData | null;
}

export function PromptsForm({ siteId, data }: PromptsFormProps) {
  const { fetchSites } = useSiteContext();
  const [articlePrompt, setArticlePrompt] = useState(data?.config?.article_prompt || data?.default_article_prompt || '');
  const [imagePrompt, setImagePrompt] = useState(data?.config?.image_prompt || data?.default_image_prompt || '');
  const [saving, setSaving] = useState(false);
  const [optimizing, setOptimizing] = useState<PromptType | null>(null);
  const [message, setMessage] = useState<StatusMessage | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    const formData = new FormData();
    formData.append('site_id', siteId.toString());
    formData.append('article_prompt', articlePrompt);
    formData.append('image_prompt', imagePrompt);
    try {
      const res = await apiFetch('/api/save-prompts', {
        method: 'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        body: formData,
      });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const result = await res.json();
      if (result.success) {
        toast.success('Prompt berhasil disimpan.');
        // Keep the cached site list in sync so other pages see the new prompts.
        fetchSites();
      } else {
        toast.error('Gagal menyimpan prompt.');
      }
    } catch {
      toast.error(NETWORK_ERROR);
    } finally {
      setSaving(false);
    }
  };

  const handleOptimize = async (type: PromptType) => {
    setOptimizing(type);
    const currentPrompt = type === 'article'
      ? (articlePrompt || data?.default_article_prompt)
      : (imagePrompt || data?.default_image_prompt);
    try {
      const res = await apiFetch('/api/optimize-prompt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ site_id: siteId, prompt_type: type, current_prompt: currentPrompt }),
      });
      if (!res.ok) {
        const errText = await res.text();
        setMessage({ text: `Kesalahan server (${res.status}): ${errText.substring(0, 150)}`, tone: 'error' });
        return;
      }
      const result = await res.json();
      if (result.success) {
        (type === 'article' ? setArticlePrompt : setImagePrompt)(result.optimized_prompt);
        setMessage({ text: 'Prompt berhasil disesuaikan dengan niche Anda oleh AI!', tone: 'success' });
      } else {
        setMessage({ text: 'Gagal mengoptimasi prompt: ' + result.error, tone: 'error' });
      }
    } catch {
      setMessage({ text: NETWORK_ERROR, tone: 'error' });
    } finally {
      setOptimizing(null);
    }
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-primary to-indigo-600 dark:from-primary dark:to-indigo-400 bg-clip-text text-transparent flex items-center gap-2">
          <FileText className="h-8 w-8 text-primary" /> Perencana Konten & Prompt
        </h1>
        <p className="text-muted-foreground">Atur prompt yang dipakai untuk membuat artikel dan gambar AI.</p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        <PromptCard
          id="article_prompt"
          title="Prompt Pembuatan Artikel"
          description="Instruksi khusus untuk Gemini AI saat membuat artikel. Variabel yang tersedia:"
          variables={['topic', 'existing_titles', 'research_note', 'seo_section']}
          label="Template Prompt"
          helper="Kosongkan untuk memakai prompt bawaan sistem."
          textareaClass="min-h-[300px]"
          value={articlePrompt}
          onChange={setArticlePrompt}
          placeholder={data?.default_article_prompt}
          optimizing={optimizing === 'article'}
          optimizeDisabled={optimizing !== null}
          onOptimize={() => handleOptimize('article')}
        />

        <PromptCard
          id="image_prompt"
          title="Prompt Gambar Utama"
          description="Instruksi untuk pembuatan gambar. Variabel yang tersedia:"
          variables={['topic']}
          label="Template Prompt Gambar"
          helper="Kosongkan untuk memakai prompt gambar bawaan sistem."
          textareaClass="min-h-[100px]"
          value={imagePrompt}
          onChange={setImagePrompt}
          placeholder={data?.default_image_prompt}
          optimizing={optimizing === 'image'}
          optimizeDisabled={optimizing !== null}
          onOptimize={() => handleOptimize('image')}
          footer={
            <CardFooter className="flex flex-col items-start gap-4 border-t bg-muted/50 p-6">
              {message && (
                <p className={`text-sm ${message.tone === 'success' ? 'text-green-600' : 'text-red-600'}`}>
                  {message.text}
                </p>
              )}
              <div className="flex justify-end pt-4 border-t border-border/50 w-full">
                <Button type="submit" disabled={saving} className="w-full sm:w-auto min-w-[200px] bg-gradient-to-r from-primary to-indigo-600 hover:from-primary/90 hover:to-indigo-600/90 text-white shadow-md text-base py-6">
                  {saving ? 'Menyimpan...' : 'Simpan Prompt'}
                </Button>
              </div>
            </CardFooter>
          }
        />
      </form>
    </div>
  );
}
