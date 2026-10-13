import { Link } from 'react-router-dom';
import { Check } from 'lucide-react';

/** Free and Pro plan cards. */
export function PricingSection({ isLoggedIn }: { isLoggedIn: boolean }) {
  return (
    <section id="pricing" className="mx-auto max-w-7xl px-6 py-20 border-t border-slate-900">
      <div className="text-center max-w-3xl mx-auto mb-16">
        <h2 className="text-3xl md:text-4xl font-extrabold text-white">Rencana Harga yang Sederhana & Transparan</h2>
        <p className="mt-4 text-slate-400">
          Mulai uji coba gratis untuk melihat performanya. Upgrade kapan saja untuk mendapatkan akses fitur Pro tanpa batas.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8 max-w-4xl mx-auto">
        {/* Free Tier */}
        <div className="p-8 rounded-2xl border border-slate-900 bg-slate-950/50 flex flex-col justify-between">
          <div>
            <div className="text-slate-400 font-bold uppercase tracking-wider text-xs">Uji Coba Gratis</div>
            <div className="mt-4 text-4xl font-black text-white">Rp 0</div>
            <div className="mt-1 text-slate-500 text-sm">Gratis selamanya untuk pengetesan</div>
            
            <div className="h-px bg-slate-900 my-6" />
            
            <ul className="space-y-3.5 text-sm text-slate-300">
              <li className="flex items-center gap-2.5">
                <Check className="h-4.5 w-4.5 text-indigo-400 shrink-0" />
                <span>Bonus 5 Kredit Artikel & Gambar</span>
              </li>
              <li className="flex items-center gap-2.5">
                <Check className="h-4.5 w-4.5 text-indigo-400 shrink-0" />
                <span>Koneksi 1 Website WordPress</span>
              </li>
              <li className="flex items-center gap-2.5">
                <Check className="h-4.5 w-4.5 text-indigo-400 shrink-0" />
                <span>Akses Riset SEO Dasar</span>
              </li>
              <li className="flex items-center gap-2.5 text-slate-500 line-through">
                <span>Integrasi Sosial Media (Auto-Share)</span>
              </li>
              <li className="flex items-center gap-2.5 text-slate-500 line-through">
                <span>Kustomisasi Model & Prompt Lanjutan</span>
              </li>
            </ul>
          </div>
          
          <div className="mt-8">
            <Link 
              to="/register" 
              className="flex items-center justify-center w-full h-11 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-200 border border-slate-800 hover:text-white transition-colors text-sm font-medium"
            >
              Daftar Sekarang
            </Link>
          </div>
        </div>

        {/* Pro Tier */}
        <div className="p-8 rounded-2xl border-2 border-indigo-500 bg-slate-950 flex flex-col justify-between relative shadow-xl shadow-indigo-500/5">
          <div className="absolute top-0 right-6 -translate-y-1/2 px-3 py-1 rounded-full bg-indigo-500 text-white text-[10px] font-bold uppercase tracking-wider">
            Paling Populer
          </div>

          <div>
            <div className="text-indigo-400 font-bold uppercase tracking-wider text-xs">Paket Pro</div>
            <div className="mt-4 text-4xl font-black text-white flex items-baseline gap-1">
              <span>Top-up Kredit</span>
              <span className="text-xs text-slate-400 font-normal">/ fleksibel</span>
            </div>
            <div className="mt-1 text-slate-400 text-sm">Mulai dari Rp 50.000 untuk pengisian ulang</div>
            
            <div className="h-px bg-indigo-950/50 my-6" />
            
            <ul className="space-y-3.5 text-sm text-slate-300">
              <li className="flex items-center gap-2.5">
                <Check className="h-4.5 w-4.5 text-indigo-400 shrink-0" />
                <span className="font-medium text-indigo-200">Semua Fitur Terbuka Penuh</span>
              </li>
              <li className="flex items-center gap-2.5">
                <Check className="h-4.5 w-4.5 text-indigo-400 shrink-0" />
                <span>Koneksi Multi WordPress</span>
              </li>
              <li className="flex items-center gap-2.5">
                <Check className="h-4.5 w-4.5 text-indigo-400 shrink-0" />
                <span>Akses Riset SEO Deep Research (100% Otomatis)</span>
              </li>
              <li className="flex items-center gap-2.5">
                <Check className="h-4.5 w-4.5 text-indigo-400 shrink-0" />
                <span>Integrasi Sosial Media (Telegram, FB, X, Threads)</span>
              </li>
              <li className="flex items-center gap-2.5">
                <Check className="h-4.5 w-4.5 text-indigo-400 shrink-0" />
                <span>Pilihan Model Gemini 3.5 & Prompt Kustom</span>
              </li>
            </ul>
          </div>
          
          <div className="mt-8 flex flex-col gap-2">
            <Link 
              to={isLoggedIn ? "/billing" : "/register"} 
              className="flex items-center justify-center w-full h-11 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold shadow-md shadow-indigo-600/10 text-sm"
            >
              Upgrade ke Pro
            </Link>
            <span className="text-[10px] text-center text-slate-500">
              Pembayaran via Transfer Manual Bank. Konfirmasi instan ke WhatsApp Admin.
            </span>
          </div>
        </div>
      </div>
    </section>
  );
}
