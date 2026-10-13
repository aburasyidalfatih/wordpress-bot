import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Bot, Info } from 'lucide-react';
import { useSiteContext } from '@/hooks/useSiteContext';
import { useParticleCanvas } from '@/hooks/useParticleCanvas';
import { apiFetch, NETWORK_ERROR } from '@/lib/api';
import { GOOGLE_IDENTITY_SCRIPT, type GoogleCredentialResponse } from '@/lib/googleIdentity';
import type { LoginResponse } from '@/lib/types';

interface LoginProps {
  setIsAuthenticated: (val: boolean) => void;
  setUserRole: (val: string) => void;
}

// Login endpoints answer 401 for bad credentials; that must not trigger
// apiFetch's redirect to /login. A stale token from an old session is not sent.
function postLogin(url: string, body: unknown): Promise<LoginResponse> {
  return apiFetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    redirectOnUnauthorized: false,
    sendToken: false,
  }).then(res => res.json());
}

const INPUT_CLASS = 'rounded-xl border-slate-800 bg-slate-900/30 text-slate-200 focus-visible:ring-indigo-500/50';

export default function Login({ setIsAuthenticated, setUserRole }: LoginProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [googleClientId, setGoogleClientId] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [simEmail, setSimEmail] = useState('demo-user@autowp.web.id');
  const navigate = useNavigate();
  const { fetchSites } = useSiteContext();
  const googleBtnRef = useRef<HTMLDivElement>(null);
  const canvasRef = useParticleCanvas();

  // Fetch the Google client id from the backend
  useEffect(() => {
    apiFetch('/api/auth/config', { redirectOnUnauthorized: false })
      .then(res => res.json())
      .then(data => {
        if (data.success && data.google_client_id) {
          setGoogleClientId(data.google_client_id);
        }
        setIsLoading(false);
      })
      .catch(err => {
        if (import.meta.env.DEV) console.error('Failed to load auth config:', err);
        setIsLoading(false);
      });
  }, []);

  /** Sends the credentials and enters the app on success. */
  const login = async (url: string, body: unknown, successMessage: string, failureMessage: string) => {
    try {
      const data = await postLogin(url, body);
      if (!data.success) {
        toast.error(data.error || failureMessage);
        return;
      }
      if (data.token) localStorage.setItem('token', data.token);
      // Load the user's sites before entering the app (no page reload happens).
      await fetchSites();
      setIsAuthenticated(true);
      if (data.user?.role) setUserRole(data.user.role);
      toast.success(successMessage);
      navigate('/dashboard');
    } catch {
      toast.error(NETWORK_ERROR);
    }
  };

  const handleCredentialResponse = (response: GoogleCredentialResponse) =>
    login('/api/auth/google', { id_token: response.credential }, 'Login Google berhasil!', 'Login Google gagal.');

  const callbackRef = useRef(handleCredentialResponse);
  useEffect(() => { callbackRef.current = handleCredentialResponse; });

  // Load and initialize Google Identity Services
  useEffect(() => {
    if (!googleClientId) return;

    const script = document.createElement('script');
    script.src = GOOGLE_IDENTITY_SCRIPT;
    script.async = true;
    script.defer = true;
    document.body.appendChild(script);

    script.onload = () => {
      if (!window.google) return;
      window.google.accounts.id.initialize({
        client_id: googleClientId,
        callback: (response) => callbackRef.current(response),
        auto_select: false,
      });
      if (googleBtnRef.current) {
        window.google.accounts.id.renderButton(googleBtnRef.current, {
          theme: 'filled_blue',
          size: 'large',
          width: 320,
          text: 'continue_with',
          shape: 'pill',
        });
      }
    };

    return () => {
      // Remove the script if the component unmounts (it may already be gone).
      script.remove();
    };
  }, [googleClientId]);

  // Fallback Google login for local/test setups without a Google client id
  const handleSimulatedGoogleLogin = () => {
    if (!simEmail) return;
    login('/api/auth/google', { id_token: `mock_token_for_${simEmail}` }, 'Simulasi login Google berhasil!', 'Login Google gagal.');
  };

  const handleAdminLogin = (e: React.FormEvent) => {
    e.preventDefault();
    login('/api/login', { email, password }, 'Login Admin berhasil!', 'Email atau password salah.');
  };

  return (
    <div className="flex h-screen w-full items-center justify-center bg-slate-950 px-4 text-slate-100 relative overflow-hidden">
      {/* Spider Web Animation Canvas */}
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full pointer-events-none z-0" />

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
                  <span>Mode Simulasi aktif. Untuk tombol Google asli, masukkan Client ID di Panel Admin.</span>
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
                <Label htmlFor="email" className="text-xs text-slate-400">Email</Label>
                <Input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="admin@example.com"
                  required
                  className={INPUT_CLASS}
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
                  className={INPUT_CLASS}
                />
              </div>
            </div>

            <Button type="submit" className="w-full py-5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold shadow-md shadow-indigo-600/10 cursor-pointer">
              Masuk
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
