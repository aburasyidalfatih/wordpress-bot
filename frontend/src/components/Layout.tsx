import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  FileText,
  Search,
  Settings,
  LogOut,
  Bot,
  ListTodo,
  Menu,
  X,
  Sun,
  Moon,
  Bell,
  Shield,
  CreditCard,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { apiFetch } from '@/lib/api';
import { useProfile } from '@/hooks/useProfile';
import { useDarkMode } from '@/hooks/useDarkMode';
import { CreditsBadge } from '@/components/layout/CreditsBadge';
import { SiteSelector } from '@/components/layout/SiteSelector';
import { ProfileMenu } from '@/components/layout/ProfileMenu';

const NAVIGATION = [
  { name: 'Dashboard', href: '/dashboard', icon: LayoutDashboard },
  { name: 'Website', href: '/sites', icon: Bot },
  { name: 'Riset', href: '/research', icon: Search },
  { name: 'Antrean', href: '/queue', icon: ListTodo },
  { name: 'Perencana Konten', href: '/prompts', icon: FileText },
  { name: 'Tagihan', href: '/billing', icon: CreditCard },
  { name: 'Pengaturan', href: '/settings', icon: Settings },
];
const ADMIN_NAVIGATION = { name: 'Panel Admin', href: '/admin', icon: Shield };

const navLinkClass = (active: boolean, layout: string) =>
  `flex items-center ${layout} rounded-xl px-4 py-3 text-sm font-medium transition-all duration-200 ${
    active
      ? 'bg-primary text-primary-foreground shadow-lg shadow-primary/20 scale-[1.02]'
      : 'text-muted-foreground hover:bg-secondary hover:text-foreground'
  }`;

async function logout() {
  try {
    await apiFetch('/logout', { method: 'POST' });
  } catch {
    // The logout endpoint may not exist; the token is dropped either way.
  }
  localStorage.removeItem('token');
  window.location.href = '/login';
}

export default function Layout({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const { isDarkMode, toggleDarkMode } = useDarkMode();
  const profile = useProfile();
  const navigation = profile.role === 'admin' ? [...NAVIGATION, ADMIN_NAVIGATION] : NAVIGATION;
  const themeIcon = isDarkMode ? <Sun className="h-5 w-5 text-yellow-500" /> : <Moon className="h-5 w-5" />;

  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground transition-colors duration-300">

      {/* Sidebar for Desktop */}
      <div className="hidden md:flex w-64 flex-col border-r bg-card/60 px-4 py-6 backdrop-blur-md">
        <div className="flex items-center gap-3 px-3 pb-8">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-tr from-primary to-indigo-600 text-primary-foreground shadow-md">
            <Bot className="h-5.5 w-5.5" />
          </div>
          <span className="text-xl font-bold font-heading bg-gradient-to-r from-primary to-indigo-600 dark:from-primary dark:to-violet-400 bg-clip-text text-transparent">
            AutoWP SaaS
          </span>
        </div>

        <nav className="flex-1 space-y-1.5">
          {navigation.map((item) => (
            <Link key={item.name} to={item.href} className={navLinkClass(location.pathname === item.href, 'gap-3.5')}>
              <item.icon className="h-5 w-5 shrink-0" />
              {item.name}
            </Link>
          ))}
        </nav>

        {/* Theme control */}
        <div className="pt-4 border-t">
          <Button
            variant="ghost"
            onClick={toggleDarkMode}
            className="w-full justify-start gap-3.5 text-muted-foreground hover:text-foreground rounded-xl"
          >
            {themeIcon}
            {isDarkMode ? 'Mode Terang' : 'Mode Gelap'}
          </Button>
        </div>
      </div>

      <div className="flex flex-col flex-1 overflow-hidden">
        {/* Mobile Top Bar */}
        <header className="flex md:hidden items-center justify-between px-6 py-4 border-b bg-card/60 backdrop-blur-md">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Bot className="h-5 w-5" />
            </div>
            <span className="text-lg font-bold bg-gradient-to-r from-primary to-indigo-600 bg-clip-text text-transparent">AutoWP</span>
          </div>
          <div className="flex items-center gap-2">
            <CreditsBadge profile={profile} compact />
            <Button variant="ghost" size="icon" onClick={toggleDarkMode} className="rounded-lg">
              {themeIcon}
            </Button>
            <Button variant="ghost" size="icon" onClick={() => setIsMobileMenuOpen(true)} className="rounded-lg">
              <Menu className="h-6 w-6" />
            </Button>
          </div>
        </header>

        {/* Desktop Top Bar */}
        <header className="hidden md:flex items-center justify-between px-8 py-3 border-b bg-card/40 backdrop-blur-md z-10 sticky top-0">
          <div className="flex items-center gap-3 text-sm font-medium">
            <span className="text-muted-foreground font-semibold">Website:</span>
            <SiteSelector />
          </div>
          <div className="flex items-center gap-4">
            {/* Placeholder search; only shown where the header has room for it,
                otherwise it pushes the credits badge and profile menu off-screen. */}
            <div className="relative hidden xl:block">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <input
                type="search"
                placeholder="Cari..."
                disabled
                aria-label="Pencarian (segera hadir)"
                className="h-9 w-64 rounded-full border border-input bg-background/50 pl-9 pr-4 text-sm ring-offset-background transition-all focus:w-72 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 disabled:cursor-not-allowed"
              />
            </div>
            <Button variant="ghost" size="icon" className="rounded-full relative hover:bg-secondary">
              <Bell className="h-5 w-5 text-muted-foreground" />
            </Button>
            <CreditsBadge profile={profile} />
            <ProfileMenu profile={profile} isDarkMode={isDarkMode} onToggleDarkMode={toggleDarkMode} onLogout={logout} />
          </div>
        </header>

        {/* Main Content Area */}
        <main className="flex-1 overflow-y-auto bg-background/90 transition-colors duration-300">
          <div className="mx-auto max-w-6xl p-6 md:p-8">
            {children}
          </div>
        </main>
      </div>

      {/* Mobile Slide-over Drawer Overlay */}
      {isMobileMenuOpen && (
        <div className="fixed inset-0 z-50 flex md:hidden bg-background/60 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="w-72 bg-card p-6 flex flex-col border-r shadow-2xl animate-in slide-in-from-left duration-300">
            <div className="flex items-center justify-between pb-8">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary text-primary-foreground">
                  <Bot className="h-5.5 w-5.5" />
                </div>
                <span className="text-xl font-bold bg-gradient-to-r from-primary to-indigo-600 bg-clip-text text-transparent">AutoWP</span>
              </div>
              <Button variant="ghost" size="icon" onClick={() => setIsMobileMenuOpen(false)} className="rounded-lg">
                <X className="h-6 w-6" />
              </Button>
            </div>

            <nav className="flex-1 space-y-2">
              <div className="mb-6 space-y-2">
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider px-4">Website Aktif</span>
                <div className="px-4">
                  <SiteSelector mobile />
                </div>
              </div>
              <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider px-4">Menu</span>
              {navigation.map((item) => (
                <Link
                  key={item.name}
                  to={item.href}
                  onClick={() => setIsMobileMenuOpen(false)}
                  className={navLinkClass(location.pathname === item.href, 'gap-4')}
                >
                  <item.icon className="h-5 w-5" />
                  {item.name}
                </Link>
              ))}
            </nav>

            <div className="pt-6 border-t">
              <Button
                variant="ghost"
                className="w-full justify-start gap-4 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-xl"
                onClick={logout}
              >
                <LogOut className="h-5 w-5" />
                Keluar
              </Button>
            </div>
          </div>
          <div className="flex-1" onClick={() => setIsMobileMenuOpen(false)} />
        </div>
      )}

    </div>
  );
}
