import { Link } from 'react-router-dom';
import { ArrowRight, Sparkles } from 'lucide-react';

/** Headline, call to action and the dashboard mockup. */
export function HeroSection({ isLoggedIn }: { isLoggedIn: boolean }) {
  return (
    <section className="relative mx-auto max-w-7xl px-6 pt-20 pb-24 md:pt-32 md:pb-36 text-center">
      {/* Badge */}
      <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-indigo-500/30 bg-indigo-500/5 text-xs text-indigo-400 font-semibold mb-6 animate-pulse">
        <Sparkles className="h-3.5 w-3.5" />
        <span>SaaS Autopilot WordPress Terlengkap</span>
      </div>

      {/* Headline */}
      <h1 className="text-4xl md:text-6xl font-extrabold tracking-tight text-white max-w-4xl mx-auto leading-[1.15] md:leading-[1.1]">
        Autopilot WordPress Anda dengan{' '}
        <span className="bg-gradient-to-r from-indigo-400 via-violet-400 to-pink-400 bg-clip-text text-transparent">
          Riset SEO & AI Konten
        </span>
      </h1>

      {/* Sub-headline */}
      <p className="mt-6 text-lg md:text-xl text-slate-400 max-w-2xl mx-auto leading-relaxed">
        Tulis artikel berkualitas tinggi, riset tren SEO terkini secara otomatis, buat featured image memukau, dan bagikan instan ke Telegram, Facebook, X (Twitter) & Threads 24/7.
      </p>

      {/* CTAs */}
      <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-4">
        <Link 
          to={isLoggedIn ? "/dashboard" : "/register"} 
          className="inline-flex items-center justify-center h-12 px-8 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-base shadow-lg shadow-indigo-600/20 transition-all duration-200 hover:scale-[1.02]"
        >
          {isLoggedIn ? "Masuk ke Dashboard" : "Mulai Sekarang - Gratis 5 Kredit"}
          <ArrowRight className="ml-2 h-5 w-5" />
        </Link>
        <a 
          href="#features"
          className="inline-flex items-center justify-center h-12 px-8 rounded-xl border border-slate-800 bg-slate-900/40 text-slate-300 hover:bg-slate-900 hover:text-white transition-colors font-semibold text-base"
        >
          Pelajari Fitur
        </a>
      </div>

      {/* Visual Mockup Container */}
      <div aria-hidden="true" className="mt-16 md:mt-20 relative rounded-2xl border border-slate-900 bg-slate-900/10 p-2 backdrop-blur-sm max-w-5xl mx-auto overflow-hidden shadow-2xl shadow-indigo-500/5">
        <div className="absolute inset-0 bg-gradient-to-t from-slate-950 via-transparent to-transparent z-10" />
        <div className="rounded-xl border border-slate-900 bg-slate-950/85 p-6 md:p-8 flex flex-col gap-6 text-left">
          {/* Mockup Topbar */}
          <div className="flex items-center justify-between border-b border-slate-900 pb-4">
            <div className="flex items-center gap-2">
              <span className="w-3 h-3 rounded-full bg-rose-500" />
              <span className="w-3 h-3 rounded-full bg-amber-500" />
              <span className="w-3 h-3 rounded-full bg-emerald-500" />
            </div>
            <div className="px-4 py-1 rounded-md bg-slate-900 text-xs text-slate-500 font-mono select-none">
              https://autowp.web.id/dashboard
            </div>
            <div className="w-12" />
          </div>
          
          {/* Mockup Dashboard Content Grid */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="p-4 rounded-xl border border-slate-900 bg-slate-900/30 flex flex-col gap-2">
              <div className="text-slate-500 text-xs font-semibold uppercase tracking-wider">Artikel Terpublish</div>
              <div className="text-2xl font-bold text-white flex items-center justify-between">
                <span>142</span>
                <span className="text-xs text-emerald-400 bg-emerald-400/10 px-2 py-0.5 rounded-full font-medium">+12 hari ini</span>
              </div>
            </div>
            <div className="p-4 rounded-xl border border-slate-900 bg-slate-900/30 flex flex-col gap-2">
              <div className="text-slate-500 text-xs font-semibold uppercase tracking-wider">Rata-rata Skor SEO</div>
              <div className="text-2xl font-bold text-white flex items-center justify-between">
                <span>94/100</span>
                <span className="text-xs text-indigo-400 bg-indigo-400/10 px-2 py-0.5 rounded-full font-medium">Optimal</span>
              </div>
            </div>
            <div className="p-4 rounded-xl border border-slate-900 bg-slate-900/30 flex flex-col gap-2">
              <div className="text-slate-500 text-xs font-semibold uppercase tracking-wider">Sosial Media Terintegrasi</div>
              <div className="text-2xl font-bold text-indigo-400 flex items-center gap-2">
                <span className="text-white">4</span>
                <span className="text-xs text-slate-500 font-normal">(FB, Tele, X, Threads)</span>
              </div>
            </div>
          </div>

          {/* Mockup Logs */}
          <div className="rounded-lg bg-slate-900/40 p-4 border border-slate-900/80 font-mono text-xs text-slate-400 space-y-2.5">
            <div className="flex items-center gap-2 text-indigo-400">
              <span className="text-slate-600">[08:00:02]</span> 🔍 Memulai riset trending topik harian untuk kategori "Teknologi"...
            </div>
            <div className="flex items-center gap-2 text-indigo-400">
              <span className="text-slate-600">[08:02:15]</span> 💡 Topik ditemukan: "Perkembangan AI Model Terbaru 2026". Skor tren: 92%
            </div>
            <div className="flex items-center gap-2 text-violet-400">
              <span className="text-slate-600">[08:02:18]</span> ✍️ Menulis artikel dengan Gemini 3.5 (Bahasa Indonesia, SEO Optimized)...
            </div>
            <div className="flex items-center gap-2 text-pink-400">
              <span className="text-slate-600">[08:03:02]</span> 🎨 Mengenerate Featured Image representatif menggunakan model visual AI...
            </div>
            <div className="flex items-center gap-2 text-emerald-400">
              <span className="text-slate-600">[08:03:45]</span> ✅ Artikel sukses dipublish ke WordPress. Post ID: 5218. URL: autowp.web.id/post-ai
            </div>
            <div className="flex items-center gap-2 text-blue-400">
              <span className="text-slate-600">[08:03:48]</span> 🚀 Membagikan otomatis ke Telegram Channel, Facebook Page, & Threads... Sukses!
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
