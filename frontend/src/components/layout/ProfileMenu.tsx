import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Settings, LogOut, Sun, Moon, ChevronDown } from 'lucide-react';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import type { UserProfile } from '@/lib/types';

interface ProfileMenuProps {
  profile: UserProfile;
  isDarkMode: boolean;
  onToggleDarkMode: () => void;
  onLogout: () => void;
}

const ITEM_CLASS = 'relative flex w-full cursor-pointer select-none items-center gap-2 rounded-sm px-2 py-2 text-sm outline-none';

export function ProfileMenu({ profile, isDarkMode, onToggleDarkMode, onLogout }: ProfileMenuProps) {
  const [isOpen, setIsOpen] = useState(false);
  const close = () => setIsOpen(false);

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="outline-none flex items-center gap-2 rounded-full ring-2 ring-background shadow-sm hover:opacity-90 hover:ring-primary/20 transition-all bg-background pl-1 pr-3 py-1"
      >
        <Avatar className="h-8 w-8">
          <AvatarImage src="https://api.dicebear.com/7.x/notionists/svg?seed=AutoWP" alt="@autowp" />
          <AvatarFallback className="bg-gradient-to-tr from-primary to-indigo-600 text-white font-bold text-xs">AW</AvatarFallback>
        </Avatar>
        <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <>
          <div className="fixed inset-0 z-40" onClick={close} />
          <div className="absolute right-0 mt-2 w-56 rounded-xl bg-popover p-1 text-popover-foreground shadow-md ring-1 ring-border animate-in fade-in zoom-in-95 duration-100 z-50">
            <div className="px-2 py-2 text-sm">
              <div className="flex flex-col space-y-1">
                <p className="font-medium leading-none">{profile.name || 'Pengguna AutoWP'}</p>
                <p className="text-xs leading-none text-muted-foreground mt-1">{profile.email || 'admin@autowp.test'}</p>
              </div>
            </div>
            <div className="h-px bg-border my-1" />
            <Link to="/settings" onClick={close} className={`${ITEM_CLASS} hover:bg-accent hover:text-accent-foreground`}>
              <Settings className="h-4 w-4" />
              <span>Pengaturan</span>
            </Link>
            <button onClick={() => { close(); onToggleDarkMode(); }} className={`${ITEM_CLASS} hover:bg-accent hover:text-accent-foreground`}>
              {isDarkMode ? <Sun className="h-4 w-4 text-yellow-500" /> : <Moon className="h-4 w-4" />}
              <span>Ganti Tema</span>
            </button>
            <div className="h-px bg-border my-1" />
            <button
              onClick={() => { close(); onLogout(); }}
              className={`${ITEM_CLASS} text-red-600 hover:bg-red-100 hover:text-red-700 dark:hover:bg-red-900/30`}
            >
              <LogOut className="h-4 w-4" />
              <span>Keluar</span>
            </button>
          </div>
        </>
      )}
    </div>
  );
}
