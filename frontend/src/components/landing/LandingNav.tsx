import { Link } from 'react-router-dom';
import { Bot, ArrowRight } from 'lucide-react';

/** Sticky top navigation of the landing page. */
export function LandingNav({ isLoggedIn }: { isLoggedIn: boolean }) {
  return (
    <nav className="sticky top-0 z-50 w-full border-b border-slate-900 bg-slate-950/80 backdrop-blur-md">
      <div className="mx-auto max-w-7xl px-6 h-16 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-tr from-indigo-500 to-violet-600 text-white shadow-lg shadow-indigo-500/20">
            <Bot className="h-5.5 w-5.5" />
          </div>
          <span className="text-xl font-bold bg-gradient-to-r from-white via-indigo-200 to-violet-400 bg-clip-text text-transparent">
            AutoWP
          </span>
        </div>

        <div className="hidden md:flex items-center gap-8 text-sm font-medium text-slate-400">
          <a href="#features" className="hover:text-white transition-colors">Fitur</a>
          <a href="#workflow" className="hover:text-white transition-colors">Cara Kerja</a>
          <a href="#pricing" className="hover:text-white transition-colors">Harga</a>
          <a href="#faq" className="hover:text-white transition-colors">FAQ</a>
        </div>

        <div className="flex items-center gap-4">
          {isLoggedIn ? (
            <Link 
              to="/dashboard" 
              className="inline-flex items-center justify-center rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-medium shadow-md shadow-indigo-600/10 transition-all duration-200 hover:scale-[1.02] px-4 py-2 text-sm"
            >
              Ke Dashboard <ArrowRight className="ml-1.5 h-4 w-4" />
            </Link>
          ) : (
            <>
              <Link to="/login" className="text-sm font-medium text-slate-300 hover:text-white transition-colors">
                Masuk
              </Link>
              <Link 
                to="/register" 
                className="inline-flex items-center justify-center rounded-xl bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 text-white font-medium shadow-md shadow-indigo-600/10 transition-all duration-200 hover:scale-[1.02] px-4 py-2 text-sm"
              >
                Coba Gratis
              </Link>
            </>
          )}
        </div>
      </div>
    </nav>
  );
}
