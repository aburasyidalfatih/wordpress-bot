import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Bot, Info } from 'lucide-react';

declare global {
  interface Window {
    google?: any;
  }
}

export default function Login({ setIsAuthenticated, setUserRole }: { setIsAuthenticated: (val: boolean) => void; setUserRole: (val: string) => void }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [googleClientId, setGoogleClientId] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const navigate = useNavigate();
  const googleBtnRef = useRef<HTMLDivElement>(null);
  const [simEmail, setSimEmail] = useState('demo-user@autowp.web.id');

  // Fetch config from backend
  useEffect(() => {
    fetch('/api/auth/config')
      .then(res => res.json())
      .then(data => {
        if (data.success && data.google_client_id) {
          setGoogleClientId(data.google_client_id);
        }
        setIsLoading(false);
      })
      .catch(err => {
        console.error("Failed to load auth config:", err);
        setIsLoading(false);
      });
  }, []);

  const handleCredentialResponse = async (response: any) => {
    const id_token = response.credential;
    try {
      const res = await fetch('/api/auth/google', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id_token }),
      });
      const data = await res.json();
      if (data.success) {
        localStorage.setItem('token', data.token);
        setIsAuthenticated(true);
        if (data.user && data.user.role) {
          setUserRole(data.user.role);
        }
        toast.success('Login Google berhasil!');
        navigate('/dashboard');
      } else {
        toast.error(data.error || 'Google login gagal');
      }
    } catch (err) {
      toast.error('Gagal menghubungi server');
    }
  };

  // Load and initialize Google GIS
  useEffect(() => {
    if (!googleClientId) return;

    // Load GIS script dynamically
    const script = document.createElement('script');
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true;
    script.defer = true;
    document.body.appendChild(script);

    script.onload = () => {
      if (window.google) {
        window.google.accounts.id.initialize({
          client_id: googleClientId,
          callback: handleCredentialResponse,
          auto_select: false
        });
        if (googleBtnRef.current) {
          window.google.accounts.id.renderButton(googleBtnRef.current, {
            theme: 'filled_blue',
            size: 'large',
            width: 320,
            text: 'continue_with',
            shape: 'pill'
          });
        }
      }
    };

    return () => {
      // Clean up script if component unmounts before loading
      try {
        document.body.removeChild(script);
      } catch (e) {
        // Ignore if script was already removed or not found
      }
    };
  }, [googleClientId]);

  // Fallback Google Login for Simulation
  const handleSimulatedGoogleLogin = async () => {
    if (!simEmail) return;
    
    try {
      const res = await fetch('/api/auth/google', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id_token: `mock_token_for_${simEmail}` }),
      });
      const data = await res.json();
      if (data.success) {
        localStorage.setItem('token', data.token);
        setIsAuthenticated(true);
        if (data.user && data.user.role) {
          setUserRole(data.user.role);
        }
        toast.success('Simulasi login Google berhasil!');
        navigate('/dashboard');
      } else {
        toast.error(data.error || 'Google login gagal');
      }
    } catch (err) {
      toast.error('Gagal menghubungi server');
    }
  };

  const handleAdminLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await fetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      if (data.success) {
        localStorage.setItem('token', data.token);
        setIsAuthenticated(true);
        if (data.user && data.user.role) {
          setUserRole(data.user.role);
        }
        toast.success('Login Admin berhasil!');
        navigate('/dashboard');
      } else {
        toast.error(data.error || 'Email atau password salah');
      }
    } catch (err) {
      toast.error('Gagal menghubungi server');
    }
  };

  return (
    <div className="flex h-screen w-full items-center justify-center bg-slate-950 px-4 text-slate-100 relative overflow-hidden">
      {/* Background decoration */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[400px] h-[400px] bg-indigo-500/5 rounded-full blur-[100px] pointer-events-none" />

      <Card className="w-full max-w-sm border-slate-900 bg-slate-950/80 backdrop-blur-md shadow-2xl relative z-10 p-2">
        <CardHeader className="text-center pb-4">
          <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-tr from-indigo-500 to-violet-600 text-white shadow-lg mb-3">
            <Bot className="h-5.5 w-5.5" />
          </div>
          <CardTitle className="text-2xl font-bold bg-gradient-to-r from-white via-indigo-100 to-slate-300 bg-clip-text text-transparent">
            Selamat Datang di AutoWP
          </CardTitle>
          <CardDescription className="text-slate-400 text-xs mt-1">
            Masuk atau daftar otomatis secara instan
          </CardDescription>
        </CardHeader>
        
        <CardContent className="grid gap-5">
          {/* Google Login Area */}
          <div className="flex flex-col items-center justify-center gap-2 py-1 w-full min-h-[50px]">
            {isLoading ? (
              <div className="h-10 w-full animate-pulse rounded-full bg-slate-900" />
            ) : googleClientId ? (
              <div ref={googleBtnRef} className="w-full flex justify-center" />
            ) : (
              <div className="w-full flex flex-col gap-3">
                <div className="grid gap-1.5 text-left">
                  <Label htmlFor="simEmail" className="text-[10px] text-slate-400">Email Simulasi (Hanya Lokal/Test)</Label>
                  <Input
                    id="simEmail"
                    type="email"
                    value={simEmail}
                    onChange={(e) => setSimEmail(e.target.value)}
                    placeholder="nama@domain.com"
                    className="h-8 rounded-lg border-slate-800 bg-slate-900/30 text-xs text-slate-200 focus-visible:ring-indigo-500/50"
                  />
                </div>
                
                <Button 
                  type="button" 
                  variant="outline" 
                  className="w-full gap-2.5 py-4 rounded-xl border-slate-800 bg-slate-900/40 text-slate-300 hover:bg-slate-900 hover:text-white transition-colors cursor-pointer text-xs"
                  onClick={handleSimulatedGoogleLogin}
                >
                  Simulasi Masuk Google
                </Button>
                
                <div className="flex gap-2 rounded-xl bg-indigo-950/20 border border-indigo-950 p-3 text-[10px] text-indigo-400 text-left">
                  <Info className="h-4 w-4 shrink-0" />
                  <span>Mode Simulasi aktif. Untuk tombol Google asli, masukkan Client ID di Admin Panel.</span>
                </div>
              </div>
            )}
          </div>

          {/* Divider */}
          <div className="relative w-full">
            <div className="absolute inset-0 flex items-center">
              <span className="w-full border-t border-slate-900" />
            </div>
            <div className="relative flex justify-center text-[10px] uppercase">
              <span className="bg-slate-950 px-2 text-slate-500 font-semibold tracking-wider">Atau</span>
            </div>
          </div>

          {/* Admin Login Form */}
          <form onSubmit={handleAdminLogin} className="flex flex-col gap-4">
            
            <div className="grid gap-3">
              <div className="grid gap-1.5">
                <Label htmlFor="email" className="text-xs text-slate-400">Email Admin</Label>
                <Input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="admin@example.com"
                  required
                  className="rounded-xl border-slate-800 bg-slate-900/30 text-slate-200 focus-visible:ring-indigo-500/50"
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="password" className="text-xs text-slate-400">Password</Label>
                <Input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  className="rounded-xl border-slate-800 bg-slate-900/30 text-slate-200 focus-visible:ring-indigo-500/50"
                />
              </div>
            </div>
            
            <Button type="submit" className="w-full py-5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold shadow-md shadow-indigo-600/10 cursor-pointer">
              Login
            </Button>
          </form>

        </CardContent>
      </Card>
    </div>
  );
}
