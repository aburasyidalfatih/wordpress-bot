import { useState } from 'react';
import { toast } from 'sonner';
import { Bot, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { apiFetch, NETWORK_ERROR } from '@/lib/api';
import type { AiImageProvider, AiTextProvider } from '@/lib/types';
import { ConfigInput, type ConfigFormProps } from './ConfigInput';
import {
  DEFAULT_MODELS, IMAGE_PROVIDER_OPTIONS, PRESET_MODELS, PROVIDER_LABELS, TEXT_PROVIDER_OPTIONS,
  filterModels, type AiProvider, type ModelKind, type ModelOption,
} from './aiModels';

const SELECT_CLASS = 'flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50';

type ModelField = keyof typeof DEFAULT_MODELS;
type LoadedModels = Partial<Record<AiProvider, string[]>>;

const API_KEY_FIELDS = {
  gemini: { field: 'gemini_api_key', savedFlag: 'has_gemini_api_key' },
  anthropic: { field: 'anthropic_api_key', savedFlag: 'has_anthropic_api_key' },
  openai: { field: 'openai_api_key', savedFlag: 'has_openai_api_key' },
} as const;

const MODEL_FIELDS: Record<AiProvider, { field: ModelField; kind: ModelKind; label: string }[]> = {
  gemini: [
    { field: 'gemini_model', kind: 'text', label: 'Model Teks' },
    { field: 'gemini_image_model', kind: 'image', label: 'Model Gambar' },
  ],
  anthropic: [{ field: 'anthropic_model', kind: 'text', label: 'Model Teks' }],
  openai: [
    { field: 'openai_model', kind: 'text', label: 'Model Teks' },
    { field: 'openai_image_model', kind: 'image', label: 'Model Gambar' },
  ],
};

/** Presets, then models loaded from the API, plus the saved value if it is neither. */
function modelOptions(provider: AiProvider, kind: ModelKind, loaded: string[] | undefined, current: string): ModelOption[] {
  const options = [...(PRESET_MODELS[provider][kind] ?? [])];
  const known = new Set(options.map((o) => o.value));
  for (const id of filterModels(provider, kind, loaded ?? [])) {
    if (!known.has(id)) {
      options.push({ value: id, label: id });
      known.add(id);
    }
  }
  if (current && !known.has(current)) options.unshift({ value: current, label: current });
  return options;
}

interface ProviderSectionProps extends ConfigFormProps {
  provider: AiProvider;
  usage: string[];
  loaded?: string[];
  loading: boolean;
  onLoadModels: () => void;
}

function ProviderSection({ provider, usage, loaded, loading, onLoadModels, ...props }: ProviderSectionProps) {
  const { config, setConfig } = props;
  const keyField = API_KEY_FIELDS[provider];
  return (
    <section className="space-y-3 border-t border-border/50 pt-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-semibold text-sm">{PROVIDER_LABELS[provider]}</h3>
        {usage.length > 0 && (
          <span className="text-[11px] font-semibold rounded-full bg-primary/10 text-primary px-2 py-0.5">
            Dipakai untuk {usage.join(' & ')}
          </span>
        )}
      </div>
      <ConfigInput
        {...props}
        field={keyField.field}
        savedFlag={keyField.savedFlag}
        label="API Key"
        type="password"
        placeholder={`API key ${PROVIDER_LABELS[provider]}`}
      />
      {MODEL_FIELDS[provider].map(({ field, kind, label }) => {
        const current = config[field] || DEFAULT_MODELS[field];
        return (
          <div key={field} className="space-y-2">
            <Label htmlFor={field}>{label}</Label>
            <select
              id={field}
              value={current}
              onChange={(e) => setConfig({ ...config, [field]: e.target.value })}
              className={SELECT_CLASS}
            >
              {modelOptions(provider, kind, loaded, current).map((m) => (
                <option key={m.value} value={m.value}>{m.label}</option>
              ))}
            </select>
          </div>
        );
      })}
      <Button type="button" variant="outline" size="sm" onClick={onLoadModels} disabled={loading} className="gap-2">
        <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
        {loading ? 'Memuat model...' : 'Muat daftar model dari API'}
      </Button>
    </section>
  );
}

export function AiSettingsCard(props: ConfigFormProps) {
  const { config, setConfig } = props;
  const [loadedModels, setLoadedModels] = useState<LoadedModels>({});
  const [loadingProvider, setLoadingProvider] = useState<AiProvider | null>(null);
  const textProvider: AiTextProvider = config.ai_text_provider || 'gemini';
  const imageProvider: AiImageProvider = config.ai_image_provider || 'gemini';

  const loadModels = async (provider: AiProvider) => {
    setLoadingProvider(provider);
    try {
      const res = await apiFetch('/api/admin/ai-models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // A key typed but not yet saved is used, so it can be checked first.
        body: JSON.stringify({ provider, api_key: config[API_KEY_FIELDS[provider].field] || '' }),
      });
      const data = await res.json();
      if (data.success) {
        setLoadedModels((prev) => ({ ...prev, [provider]: data.models }));
        toast.success(`${data.models.length} model ${PROVIDER_LABELS[provider]} berhasil dimuat.`);
      } else {
        toast.error(data.error || 'Gagal memuat daftar model.');
      }
    } catch {
      toast.error(NETWORK_ERROR);
    } finally {
      setLoadingProvider(null);
    }
  };

  const usageOf = (provider: AiProvider) => [
    ...(textProvider === provider ? ['teks'] : []),
    ...(imageProvider === provider ? ['gambar'] : []),
  ];

  return (
    <Card className="border-border/50 shadow-md">
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          <Bot className="h-5 w-5 text-indigo-500" /> Konfigurasi AI
        </CardTitle>
        <CardDescription>
          Pilih provider dan model AI yang dipakai bersama untuk menulis artikel, membuat judul riset, dan membuat gambar.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4">
          <div className="space-y-2">
            <Label htmlFor="ai_text_provider">Provider Teks (artikel & riset)</Label>
            <select
              id="ai_text_provider"
              value={textProvider}
              onChange={(e) => setConfig({ ...config, ai_text_provider: e.target.value as AiTextProvider })}
              className={SELECT_CLASS}
            >
              {TEXT_PROVIDER_OPTIONS.map((p) => <option key={p} value={p}>{PROVIDER_LABELS[p]}</option>)}
            </select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="ai_image_provider">Provider Gambar</Label>
            <select
              id="ai_image_provider"
              value={imageProvider}
              onChange={(e) => setConfig({ ...config, ai_image_provider: e.target.value as AiImageProvider })}
              className={SELECT_CLASS}
            >
              {IMAGE_PROVIDER_OPTIONS.map((p) => <option key={p} value={p}>{PROVIDER_LABELS[p]}</option>)}
            </select>
          </div>
        </div>
        <p className="text-xs text-muted-foreground">
          Provider yang dipilih wajib punya API key. Biaya kredit per artikel sama untuk semua provider.
        </p>
        {TEXT_PROVIDER_OPTIONS.map((provider) => (
          <ProviderSection
            key={provider}
            {...props}
            provider={provider}
            usage={usageOf(provider)}
            loaded={loadedModels[provider]}
            loading={loadingProvider === provider}
            onLoadModels={() => loadModels(provider)}
          />
        ))}
      </CardContent>
    </Card>
  );
}
