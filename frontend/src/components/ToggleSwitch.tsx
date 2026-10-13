interface ToggleSwitchProps {
  checked: boolean;
  onToggle: () => void;
  ariaLabel?: string;
  /** "md" is the default form switch; "sm" is the compact one used in tables. */
  size?: 'md' | 'sm';
}

const SIZES = {
  md: { track: 'h-6 w-11', knob: 'h-5 w-5', on: 'translate-x-5' },
  sm: { track: 'h-5 w-9', knob: 'h-4 w-4', on: 'translate-x-4' },
};

export function ToggleSwitch({ checked, onToggle, ariaLabel, size = 'md' }: ToggleSwitchProps) {
  const s = SIZES[size];
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      onClick={onToggle}
      className={`${checked ? 'bg-primary' : 'bg-muted'} relative inline-flex ${s.track} shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none`}
    >
      <span
        className={`${checked ? s.on : 'translate-x-0'} pointer-events-none inline-block ${s.knob} transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out`}
      />
    </button>
  );
}
