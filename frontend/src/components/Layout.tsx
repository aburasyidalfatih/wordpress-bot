import { useState, useEffect } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { 
  LayoutDashboard, 
  FileText, 
  Search, 
  Activity, 
  Settings,
  LogOut,
  Bot,
  ListTodo,
  Menu,
  X,
  Sun,
  Moon,
  Bell,
  ChevronDown,
  Shield,
  CreditCard,
  Coins
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { useSiteContext } from '@/contexts/SiteContext';

export default function Layout({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [isProfileOpen, setIsProfileOpen] = useState(false);
  const [isDarkMode, setIsDarkMode] = useState(() => {
    return localStorage.getItem('theme') === 'dark' || 
      (!localStorage.getItem('theme') && window.matchMedia('(prefers-color-scheme: dark)').matches);
  });
  const [profile, setProfile] = useState<{
    name?: string;
    email?: string;
    role?: string;
    tier?: string;
    credits?: number;
  }>({});

  const { sites, selectedSiteId, setSelectedSiteId, loading } = useSiteContext();

  useEffect(() => {
    import('../lib/api').then(({ apiFetch }) => {
      apiFetch('/api/profile')
        .then(res => res.json())
        .then(data => {
          if (data.success && data.profile) {
            setProfile(data.profile);
          }
        })
        .catch(console.error);
    });
  }, [location.pathname]);

  useEffect(() => {
    if (isDarkMode) {
      document.documentElement.classList.add('dark');
      localStorage.setItem('theme', 'dark');
    } else {
      document.documentElement.classList.remove('dark');
      localStorage.setItem('theme', 'light');
    }
  }, [isDarkMode]);

  const navigation = [
    { name: 'Dashboard', href: '/', icon: LayoutDashboard },
    { name: 'Websites', href: '/sites', icon: Bot },
    { name: 'Research', href: '/research', icon: Search },
    { name: 'Queue', href: '/queue', icon: ListTodo },
    { name: 'Monitor', href: '/monitor', icon: Activity },
    { name: 'Planner', href: '/prompts', icon: FileText },
    { name: 'Billing', href: '/billing', icon: CreditCard },
    { name: 'Settings', href: '/settings', icon: Settings },
    ...(profile.role === 'admin' ? [{ name: 'Admin Panel', href: '/admin', icon: Shield }] : [])
  ];

  const handleLogout = async () => {
    try {
      await fetch('/logout');
      localStorage.removeItem('token');
      navigate('/login');
      window.location.reload();
    } catch (e) {
      console.error(e);
    }
  };

  const toggleDarkMode = () => {
    setIsDarkMode(!isDarkMode);
  };

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
          {navigation.map((item) => {
            const isActive = location.pathname === item.href;
            return (
              <Link
                key={item.name}
                to={item.href}
                className={`flex items-center gap-3.5 rounded-xl px-4 py-3 text-sm font-medium transition-all duration-200 ${
                  isActive 
                    ? 'bg-primary text-primary-foreground shadow-lg shadow-primary/20 scale-[1.02]' 
                    : 'text-muted-foreground hover:bg-secondary hover:text-foreground'
                }`}
              >
                <item.icon className="h-5 w-5 shrink-0" />
                {item.name}
              </Link>
            );
          })}
        </nav>



        {/* Theme control */}
        <div className="pt-4 border-t">
          <Button 
            variant="ghost"
            onClick={toggleDarkMode}
            className="w-full justify-start gap-3.5 text-muted-foreground hover:text-foreground rounded-xl"
          >
            {isDarkMode ? <Sun className="h-5 w-5 text-yellow-500" /> : <Moon className="h-5 w-5" />}
            {isDarkMode ? 'Light Mode' : 'Dark Mode'}
          </Button>
        </div>
      </div>

      {/* Mobile Top Bar */}
      <div className="flex flex-col flex-1 overflow-hidden">
        <header className="flex md:hidden items-center justify-between px-6 py-4 border-b bg-card/60 backdrop-blur-md">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Bot className="h-5 w-5" />
            </div>
            <span className="text-lg font-bold bg-gradient-to-r from-primary to-indigo-600 bg-clip-text text-transparent">AutoWP</span>
          </div>
          <div className="flex items-center gap-2">
            {/* Mobile Credits Badge */}
            <Link to="/billing" className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-primary/10 border border-primary/25 text-primary">
              <Coins className="h-3.5 w-3.5 shrink-0 text-primary" />
              <span className="text-xs font-bold">{profile.credits !== undefined ? profile.credits : 0}</span>
            </Link>

            <Button variant="ghost" size="icon" onClick={toggleDarkMode} className="rounded-lg">
              {isDarkMode ? <Sun className="h-5 w-5 text-yellow-500" /> : <Moon className="h-5 w-5" />}
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
            {loading ? (
              <div className="h-9 w-48 animate-pulse rounded-md bg-muted"></div>
            ) : (
              <select
                value={selectedSiteId || ''}
                onChange={(e) => setSelectedSiteId(parseInt(e.target.value, 10))}
                className="h-9 w-48 rounded-lg border border-input bg-card/80 backdrop-blur-sm px-3 py-1 text-sm shadow-sm transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 hover:bg-accent cursor-pointer"
              >
                {sites.map(site => (
                  <option key={site.id} value={site.id} className="bg-background text-foreground">
                    {site.site_name}
                  </option>
                ))}
                {sites.length === 0 && <option disabled value="">No Sites Found</option>}
              </select>
            )}
          </div>
          <div className="flex items-center gap-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <input
                type="search"
                placeholder="Search..."
                className="h-9 w-64 rounded-full border border-input bg-background/50 pl-9 pr-4 text-sm ring-offset-background transition-all focus:w-72 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            </div>
            <Button variant="ghost" size="icon" className="rounded-full relative hover:bg-secondary">
              <Bell className="h-5 w-5 text-muted-foreground" />
              <span className="absolute top-1.5 right-2 h-2 w-2 rounded-full bg-red-500 animate-pulse"></span>
            </Button>

            {/* Desktop Credits Badge */}
            <Link to="/billing" className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-primary/10 hover:bg-primary/20 border border-primary/25 text-primary transition-all duration-200 hover:scale-[1.02]">
              <Coins className="h-4 w-4 shrink-0 text-primary" />
              <span className="text-xs font-bold">{profile.credits !== undefined ? profile.credits : 0} Credits</span>
              <span className="text-[10px] bg-primary/20 text-primary font-extrabold px-1.5 py-0.5 rounded-md capitalize">{profile.tier || 'free'}</span>
            </Link>
            <div className="relative">
              <button 
                onClick={() => setIsProfileOpen(!isProfileOpen)} 
                className="outline-none flex items-center gap-2 rounded-full ring-2 ring-background shadow-sm hover:opacity-90 hover:ring-primary/20 transition-all bg-background pl-1 pr-3 py-1"
              >
                <Avatar className="h-8 w-8">
                  <AvatarImage src="https://api.dicebear.com/7.x/notionists/svg?seed=AutoWP" alt="@autowp" />
                  <AvatarFallback className="bg-gradient-to-tr from-primary to-indigo-600 text-white font-bold text-xs">AW</AvatarFallback>
                </Avatar>
                <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform duration-200 ${isProfileOpen ? 'rotate-180' : ''}`} />
              </button>
              
              {isProfileOpen && (
                <>
                  <div 
                    className="fixed inset-0 z-40" 
                    onClick={() => setIsProfileOpen(false)} 
                  />
                  <div className="absolute right-0 mt-2 w-56 rounded-xl bg-popover p-1 text-popover-foreground shadow-md ring-1 ring-border animate-in fade-in zoom-in-95 duration-100 z-50">
                    <div className="px-2 py-2 text-sm">
                      <div className="flex flex-col space-y-1">
                        <p className="font-medium leading-none">{profile.name || 'AutoWP User'}</p>
                        <p className="text-xs leading-none text-muted-foreground mt-1">{profile.email || 'admin@autowp.test'}</p>
                      </div>
                    </div>
                    <div className="h-px bg-border my-1" />
                    <Link 
                      to="/settings"
                      onClick={() => setIsProfileOpen(false)} 
                      className="relative flex w-full cursor-pointer select-none items-center gap-2 rounded-sm px-2 py-2 text-sm outline-none hover:bg-accent hover:text-accent-foreground"
                    >
                      <Settings className="h-4 w-4" />
                      <span>Settings</span>
                    </Link>
                    <button 
                      onClick={() => { setIsProfileOpen(false); toggleDarkMode(); }} 
                      className="relative flex w-full cursor-pointer select-none items-center gap-2 rounded-sm px-2 py-2 text-sm outline-none hover:bg-accent hover:text-accent-foreground"
                    >
                      {isDarkMode ? <Sun className="h-4 w-4 text-yellow-500" /> : <Moon className="h-4 w-4" />}
                      <span>Toggle Theme</span>
                    </button>
                    <div className="h-px bg-border my-1" />
                    <button 
                      onClick={() => { setIsProfileOpen(false); handleLogout(); }} 
                      className="relative flex w-full cursor-pointer select-none items-center gap-2 rounded-sm px-2 py-2 text-sm outline-none text-red-600 hover:bg-red-100 hover:text-red-700 dark:hover:bg-red-900/30"
                    >
                      <LogOut className="h-4 w-4" />
                      <span>Log out</span>
                    </button>
                  </div>
                </>
              )}
            </div>
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
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider px-4">Website Workspace</span>
                <div className="px-4">
                  {loading ? (
                    <div className="h-10 w-full animate-pulse rounded-lg bg-muted"></div>
                  ) : (
                    <select
                      value={selectedSiteId || ''}
                      onChange={(e) => {
                        setSelectedSiteId(parseInt(e.target.value, 10));
                      }}
                      className="h-10 w-full rounded-lg border border-input bg-card/80 px-3 py-2 text-sm shadow-sm transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 hover:bg-accent"
                    >
                      {sites.map(site => (
                        <option key={site.id} value={site.id} className="bg-background text-foreground">
                          {site.site_name}
                        </option>
                      ))}
                      {sites.length === 0 && <option disabled value="">No Sites Found</option>}
                    </select>
                  )}
                </div>
              </div>
              <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider px-4">Menu</span>
              {navigation.map((item) => {
                const isActive = location.pathname === item.href;
                return (
                  <Link
                    key={item.name}
                    to={item.href}
                    onClick={() => setIsMobileMenuOpen(false)}
                    className={`flex items-center gap-4 rounded-xl px-4 py-3 text-sm font-medium transition-all duration-200 ${
                      isActive 
                        ? 'bg-primary text-primary-foreground shadow-lg shadow-primary/20 scale-[1.02]' 
                        : 'text-muted-foreground hover:bg-secondary hover:text-foreground'
                    }`}
                  >
                    <item.icon className="h-5 w-5" />
                    {item.name}
                  </Link>
                );
              })}
            </nav>



            <div className="pt-6 border-t">
              <Button 
                variant="ghost" 
                className="w-full justify-start gap-4 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-xl"
                onClick={handleLogout}
              >
                <LogOut className="h-5 w-5" />
                Logout
              </Button>
            </div>
          </div>
          <div className="flex-1" onClick={() => setIsMobileMenuOpen(false)} />
        </div>
      )}

    </div>
  );
}
