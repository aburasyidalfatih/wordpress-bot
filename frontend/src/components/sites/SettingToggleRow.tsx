import { Label } from '@/components/ui/label';
import { ToggleSwitch } from '@/components/ToggleSwitch';

interface SettingToggleRowProps {
  title: string;
  description: string;
  checked: boolean;
  onToggle: () => void;
  ariaLabel?: string;
  /** Smaller variant used for nested options. */
  compact?: boolean;
}

export function SettingToggleRow({ title, description, checked, onToggle, ariaLabel, compact = false }: SettingToggleRowProps) {
  return (
    <div className={`flex items-center justify-between p-4 border rounded-xl ${compact ? 'bg-muted/10' : 'bg-muted/20'}`}>
      <div className="space-y-0.5">
        <Label className={compact ? 'font-semibold text-foreground' : 'text-base font-semibold text-foreground'}>{title}</Label>
        <p className={compact ? 'text-xs text-muted-foreground' : 'text-sm text-muted-foreground'}>{description}</p>
      </div>
      <ToggleSwitch checked={checked} onToggle={onToggle} ariaLabel={ariaLabel ?? title} />
    </div>
  );
}
