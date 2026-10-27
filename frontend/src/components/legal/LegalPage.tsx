import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Bot } from 'lucide-react';

export const LEGAL_UPDATED = '28 Oktober 2026';
export const CONTACT_EMAIL = 'andriko484@gmail.com';

/** Shared layout for the public legal pages (no login required). */
export function LegalPage({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-300">
      <header className="border-b border-slate-900">
        <div className="mx-auto max-w-3xl px-6 py-5 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-3 text-white font-bold">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600">
              <Bot className="h-4.5 w-4.5" />
            </span>
            AutoWP
          </Link>
          <nav className="flex gap-5 text-sm">
            <Link to="/privacy" className="hover:text-white">Kebijakan Privasi</Link>
            <Link to="/terms" className="hover:text-white">Syarat Layanan</Link>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-6 py-12">
        <h1 className="text-3xl font-bold text-white">{title}</h1>
        <p className="mt-2 text-sm text-slate-500">Terakhir diperbarui: {LEGAL_UPDATED}</p>
        <div className="mt-8 space-y-6 leading-relaxed [&_h2]:mt-10 [&_h2]:text-xl [&_h2]:font-semibold [&_h2]:text-white [&_ul]:list-disc [&_ul]:pl-6 [&_ul]:space-y-2 [&_a]:text-indigo-400 [&_a]:underline">
          {children}
        </div>
      </main>
    </div>
  );
}
