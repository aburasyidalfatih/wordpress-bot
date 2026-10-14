import type { ResearchStats, SiteCategory } from '@/lib/types';

/** The backend clamps every title request to this many titles. */
export const MAX_TITLES_PER_REQUEST = 20;

/** Identity of a category name: case-insensitive and ignoring outer spaces. */
export function categoryKey(name: string): string {
  return name.trim().toLocaleLowerCase('id-ID');
}

/** Categories with duplicate names (see categoryKey) removed, first one kept. */
export function dedupeCategories(categories: SiteCategory[]): SiteCategory[] {
  const seen = new Set<string>();
  return categories.filter(category => {
    const key = categoryKey(category.name);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/**
 * Parses a title count typed by the user and clamps it to min..20. An empty or
 * invalid value becomes `min` (1 for a single request, 0 = "skip" in bulk).
 */
export function clampTitleCount(raw: string | number, min: 0 | 1): number {
  const value = Math.floor(Number(raw));
  if (String(raw).trim() === '' || !Number.isFinite(value)) return min;
  return Math.min(MAX_TITLES_PER_REQUEST, Math.max(min, value));
}

/** Why titles cannot be generated for a category, or null when they can. */
export function titleBlockReason(stats: ResearchStats | undefined): string | null {
  if (!stats) return 'Belum ada riset untuk kategori ini.';
  // Older backends do not send eligible_for_titles; treat their research as usable.
  if (stats.eligible_for_titles === false) {
    return stats.title_block_reason || 'Data riset kategori ini belum cukup kuat untuk membuat judul. Riset ulang terlebih dahulu.';
  }
  return null;
}
