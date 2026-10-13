import { Link } from 'react-router-dom';
import { Coins } from 'lucide-react';
import type { UserProfile } from '@/lib/types';

/** Colours by remaining credits: red when empty, amber when low. */
function badgeColors(credits: number, withHover: boolean) {
  if (credits === 0) {
    return {
      badge: `bg-red-500/10 ${withHover ? 'hover:bg-red-500/20 ' : ''}border-red-500/30 text-red-600 dark:text-red-400 animate-pulse`,
      coin: 'text-red-500',
    };
  }
  if (credits <= 2) {
    return {
      badge: `bg-amber-500/10 ${withHover ? 'hover:bg-amber-500/20 ' : ''}border-amber-500/30 text-amber-600 dark:text-amber-400`,
      coin: 'text-amber-500',
    };
  }
  return {
    badge: `bg-primary/10 ${withHover ? 'hover:bg-primary/20 ' : ''}border-primary/25 text-primary`,
    coin: 'text-primary',
  };
}

/** Credit balance link to /billing; "compact" is the mobile header variant. */
export function CreditsBadge({ profile, compact = false }: { profile: UserProfile; compact?: boolean }) {
  const credits = profile.credits ?? 0;
  const colors = badgeColors(credits, !compact);

  if (compact) {
    return (
      <Link to="/billing" className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border transition-colors ${colors.badge}`}>
        <Coins className={`h-3.5 w-3.5 shrink-0 ${colors.coin}`} />
        <span className="text-xs font-bold">{credits}</span>
      </Link>
    );
  }

  return (
    <Link to="/billing" className={`flex items-center gap-2 px-3 py-1.5 rounded-full border transition-all duration-200 hover:scale-[1.02] ${colors.badge}`}>
      <Coins className={`h-4 w-4 shrink-0 ${colors.coin}`} />
      <span className="text-xs font-bold">{credits} Kredit</span>
      <span className="text-[10px] bg-foreground/10 font-extrabold px-1.5 py-0.5 rounded-md capitalize">{profile.tier || 'free'}</span>
    </Link>
  );
}
