import { Link } from 'react-router-dom';
import { Bot } from 'lucide-react';

/** FAQ, closing call to action and the page footer. */
export function LandingFooter({ isLoggedIn }: { isLoggedIn: boolean }) {
  return (
    <>
      {/* FAQ Section */}
      <section id="faq" className="mx-auto max-w-4xl px-6 py-20 border-t border-slate-900">
        <div className="text-center mb-16">
          <h2 className="text-3xl font-extrabold text-white">Pertanyaan yang Sering Diajukan</h2>
          <p className="mt-3 text-slate-400">Punya pertanyaan lain? Kami punya jawabannya.</p>
        </div>

        <div className="space-y-6">
          <div className="p-6 rounded-xl border border-slate-900 bg-slate-950/20">
            <h4 className="text-base font-bold text-white">Bagaimana cara menghitung penggunaan kredit?</h4>
            <p className="mt-2 text-slate-400 text-sm leading-relaxed">
              Setiap artikel sukses yang berhasil di-generate beserta featured imagenya dan dipublikasikan ke WordPress akan memotong 1 kredit dari akun Anda. Proses riset dan autopost sosial media tidak memotong kredit tambahan.
            </p>
          </div>

          <div className="p-6 rounded-xl border border-slate-900 bg-slate-950/20">
            <h4 className="text-base font-bold text-white">Apakah website WordPress saya aman?</h4>
            <p className="mt-2 text-slate-400 text-sm leading-relaxed">
              Sangat aman. Kami menggunakan sistem "Application Password" resmi dari WordPress. Kami tidak meminta password login utama administrator Anda, dan Anda dapat mencabut (revoke) akses tersebut kapan pun langsung dari panel WordPress Anda.
            </p>
          </div>

          <div className="p-6 rounded-xl border border-slate-900 bg-slate-950/20">
            <h4 className="text-base font-bold text-white">Bagaimana cara kerja Transfer Manual untuk pembayaran Pro?</h4>
            <p className="mt-2 text-slate-400 text-sm leading-relaxed">
              Anda tinggal masuk ke halaman Tagihan di dalam dashboard, lalu pilih metode "Transfer Manual". Ikuti petunjuk nomor rekening yang disediakan dan klik tombol "Konfirmasi via WhatsApp" untuk mengirimkan bukti transfer secara instan ke admin.
            </p>
          </div>
        </div>
      </section>

      {/* Call to Action Footer Section */}
      <section className="relative mx-auto max-w-5xl px-6 py-16 mb-20 rounded-3xl border border-indigo-500/20 bg-gradient-to-b from-indigo-950/20 to-slate-950 text-center overflow-hidden">
        <div className="absolute inset-0 bg-indigo-500/5 blur-[80px] pointer-events-none" />
        <h2 className="text-3xl md:text-4xl font-extrabold text-white">
          Siap Meningkatkan Trafik Website Anda?
        </h2>
        <p className="mt-4 text-slate-400 max-w-xl mx-auto text-sm md:text-base">
          Dapatkan akses instan ke riset tren harian dan publikasi otomatis bertenaga AI Gemini. Coba gratis dengan 5 kredit Anda sekarang.
        </p>
        <div className="mt-8">
          <Link 
            to={isLoggedIn ? "/dashboard" : "/register"} 
            className="inline-flex items-center justify-center h-12 px-8 rounded-xl bg-white text-slate-950 hover:bg-slate-100 font-bold transition-all duration-200 hover:scale-[1.02] text-base"
          >
            {isLoggedIn ? "Masuk ke Dashboard" : "Daftar Akun Gratis Sekarang"}
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-slate-900 bg-slate-950 py-12 text-slate-500 text-sm">
        <div className="mx-auto max-w-7xl px-6 flex flex-col md:flex-row items-center justify-between gap-6">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-white">
              <Bot className="h-4.5 w-4.5" />
            </div>
            <span className="text-white font-bold">AutoWP</span>
          </div>

          <div className="flex flex-wrap items-center justify-center gap-6">
            <Link to="/privacy" className="hover:text-white">Kebijakan Privasi</Link>
            <Link to="/terms" className="hover:text-white">Syarat Layanan</Link>
            <span>&copy; {new Date().getFullYear()} AutoWP SaaS. Hak cipta dilindungi.</span>
          </div>
        </div>
      </footer>
    </>
  );
}
