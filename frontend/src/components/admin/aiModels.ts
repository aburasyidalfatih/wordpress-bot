import type { AiImageProvider, AiTextProvider } from '@/lib/types';

// Defaults must match config.py (DEFAULT_*_MODEL). These are suggestions only:
// "Muat dari API" lists every model the saved/typed key can actually use.

export interface ModelOption {
  value: string;
  label: string;
}

export type AiProvider = AiTextProvider;
export type ModelKind = 'text' | 'image';

export const PROVIDER_LABELS: Record<AiProvider, string> = {
  gemini: 'Gemini (Google)',
  anthropic: 'Claude (Anthropic)',
  openai: 'OpenAI',
};

export const TEXT_PROVIDER_OPTIONS: AiTextProvider[] = ['gemini', 'anthropic', 'openai'];
export const IMAGE_PROVIDER_OPTIONS: AiImageProvider[] = ['gemini', 'openai'];

export const DEFAULT_MODELS = {
  gemini_model: 'gemini-3.5-flash',
  gemini_image_model: 'gemini-3.1-flash-image',
  anthropic_model: 'claude-opus-5-5',
  openai_model: 'gpt-5.5',
  openai_image_model: 'gpt-image-2',
} as const;

export const PRESET_MODELS: Record<AiProvider, Partial<Record<ModelKind, ModelOption[]>>> = {
  gemini: {
    text: [
      { value: 'gemini-3.6-flash', label: 'Gemini 3.6 Flash (Terbaru)' },
      { value: 'gemini-3.6-pro', label: 'Gemini 3.6 Pro' },
      { value: 'gemini-3.5-flash', label: 'Gemini 3.5 Flash (Stabil / Direkomendasikan)' },
      { value: 'gemini-3.1-flash-lite', label: 'Gemini 3.1 Flash-Lite (Stabil)' },
      { value: 'gemini-3.1-pro-preview', label: 'Gemini 3.1 Pro (Preview)' },
      { value: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro (Lama, Stabil)' },
    ],
    image: [
      { value: 'gemini-3.1-flash-image', label: 'Gemini 3.1 Flash Image (Stabil / Direkomendasikan)' },
      { value: 'gemini-3-pro-image', label: 'Gemini 3 Pro Image (Kualitas Tinggi)' },
      { value: 'gemini-3.1-flash-lite-image', label: 'Gemini 3.1 Flash Lite Image (Cepat)' },
      { value: 'gemini-3.1-flash-image-preview', label: 'Gemini 3.1 Flash Image (Preview)' },
    ],
  },
  anthropic: {
    text: [
      { value: 'claude-opus-5-5', label: 'Claude Opus 5.5 (Direkomendasikan)' },
      { value: 'claude-sonnet-5-5', label: 'Claude Sonnet 5.5 (Lebih hemat)' },
      { value: 'claude-haiku-5-5', label: 'Claude Haiku 5.5 (Paling hemat & cepat)' },
      { value: 'claude-fable-5-1', label: 'Claude Fable 5.1 (Paling canggih, paling mahal)' },
    ],
  },
  openai: {
    text: [
      { value: 'gpt-5.5', label: 'GPT-5.5 (Direkomendasikan)' },
      { value: 'gpt-5.4', label: 'GPT-5.4' },
      { value: 'gpt-5.4-mini', label: 'GPT-5.4 mini (Hemat)' },
    ],
    image: [
      { value: 'gpt-image-2', label: 'GPT Image 2 (Direkomendasikan)' },
      { value: 'gpt-image-1.5', label: 'GPT Image 1.5' },
      { value: 'gpt-image-1-mini', label: 'GPT Image 1 mini (Hemat)' },
      { value: 'dall-e-3', label: 'DALL·E 3 (Lama)' },
    ],
  },
};

const OPENAI_NON_TEXT = /image|dall-e|audio|realtime|tts|transcribe|embedding|moderation|search|whisper|codex|computer/;

/** Keep only the models from a provider's full list that fit this slot. */
export function filterModels(provider: AiProvider, kind: ModelKind, ids: string[]): string[] {
  return ids.filter((id) => {
    if (provider === 'anthropic') return id.startsWith('claude-');
    if (provider === 'gemini') {
      const isImage = id.includes('image') || id.startsWith('imagen');
      if (kind === 'image') return isImage;
      return id.startsWith('gemini') && !isImage && !/embedding|tts|audio|live/.test(id);
    }
    if (kind === 'image') return /^(gpt-image|dall-e|chatgpt-image)/.test(id);
    return /^(gpt-|o\d|chatgpt-)/.test(id) && !OPENAI_NON_TEXT.test(id);
  });
}
