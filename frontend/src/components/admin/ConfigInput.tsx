import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { AdminConfig } from '@/lib/types';

type StringConfigKey = {
  [K in keyof AdminConfig]-?: AdminConfig[K] extends string | undefined ? K : never;
}[keyof AdminConfig];

export interface ConfigFormProps {
  config: AdminConfig;
  setConfig: (config: AdminConfig) => void;
}

interface ConfigInputProps extends ConfigFormProps {
  field: StringConfigKey;
  label: string;
  placeholder?: string;
  type?: 'text' | 'password' | 'email';
  /** For secrets: when this flag is set the stored value is never sent back, so say so. */
  savedFlag?: keyof AdminConfig;
  className?: string;
}

const SAVED_SECRET_PLACEHOLDER = 'Sudah tersimpan. Isi untuk mengganti.';

/** Text input bound to one string field of the admin config. */
export function ConfigInput({ config, setConfig, field, label, placeholder, type, savedFlag, className = 'space-y-2' }: ConfigInputProps) {
  return (
    <div className={className}>
      <Label htmlFor={field}>{label}</Label>
      <Input
        id={field}
        type={type}
        value={config[field] || ''}
        onChange={(e) => setConfig({ ...config, [field]: e.target.value })}
        placeholder={savedFlag && config[savedFlag] ? SAVED_SECRET_PLACEHOLDER : placeholder}
      />
    </div>
  );
}
