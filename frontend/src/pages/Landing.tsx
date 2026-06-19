import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { 
  Bot, 
  Search, 
  Image as ImageIcon, 
  Share2, 
  ListTodo, 
  Check, 
  ArrowRight, 
  Sparkles, 
  Globe
} from 'lucide-react';

export default function Landing() {
  const [isLoggedIn, setIsLoggedIn] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem('token');
    setIsLoggedIn(!!token);
  }, []);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-sans selection:bg-indigo-500 selection:text-white overflow-x-hidden">
      {/* Decorative background glows */}
      <div className="absolute top-0 left-1/4 -translate-x-1/2 w-[500px] h-[500px] bg-indigo-500/10 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute top-[20%] right-1/4 translate-x-1/2 w-[600px] h-[600px] bg-violet-500/10 rounded-full blur-[150px] pointer-events-none" />
      <div className="absolute bottom-[20%] left-10 w-[400px] h-[400px] bg-blue-500/5 rounded-full blur-[100px] pointer-events-none" />

      {/* Navigation */}
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

      {/* Hero Section */}
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
        <div className="mt-16 md:mt-20 relative rounded-2xl border border-slate-900 bg-slate-900/10 p-2 backdrop-blur-sm max-w-5xl mx-auto overflow-hidden shadow-2xl shadow-indigo-500/5">
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
                <span className="text-slate-600">[08:02:18]</span> ✍️ Menulis artikel dengan Gemini 2.5 Pro (Bahasa Indonesia, SEO Optimized)...
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

      {/* Features Grid */}
      <section id="features" className="mx-auto max-w-7xl px-6 py-20 border-t border-slate-900 relative">
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] bg-violet-600/5 rounded-full blur-[120px] pointer-events-none" />
        
        <div className="text-center max-w-3xl mx-auto mb-16">
          <h2 className="text-3xl md:text-4xl font-extrabold text-white">Semua Fitur Unggulan untuk Pertumbuhan Konten Anda</h2>
          <p className="mt-4 text-slate-400 leading-relaxed">
            AutoWP dirancang dari awal untuk memberikan fungsionalitas penuh agar blog WordPress dan jaringan sosial media Anda tetap aktif menghasilkan trafik organik tanpa repot.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
          {/* Feature 1 */}
          <div className="p-6 rounded-2xl border border-slate-900 bg-slate-950 hover:border-indigo-500/20 transition-all duration-300 group">
            <div className="w-12 h-12 rounded-xl bg-indigo-500/10 text-indigo-400 flex items-center justify-center group-hover:scale-110 transition-transform duration-300">
              <Search className="h-6 w-6" />
            </div>
            <h3 className="text-lg font-bold text-white mt-4">Riset SEO Otomatis</h3>
            <p className="mt-2 text-slate-400 text-sm leading-relaxed">
              Sistem secara berkala memindai Google Trends, menganalisis kompetitor, mencatat kata kunci populer, serta mengekstrak pertanyaan pengguna untuk diolah menjadi ide konten.
            </p>
          </div>

          {/* Feature 2 */}
          <div className="p-6 rounded-2xl border border-slate-900 bg-slate-950 hover:border-indigo-500/20 transition-all duration-300 group">
            <div className="w-12 h-12 rounded-xl bg-violet-500/10 text-violet-400 flex items-center justify-center group-hover:scale-110 transition-transform duration-300">
              <Sparkles className="h-6 w-6" />
            </div>
            <h3 className="text-lg font-bold text-white mt-4">Penulis AI Gemini</h3>
            <p className="mt-2 text-slate-400 text-sm leading-relaxed">
              Menggunakan model tercanggih Gemini untuk menulis konten berkualitas tinggi, natural, ramah SEO, dan lengkap dengan meta description serta tag yang sesuai.
            </p>
          </div>

          {/* Feature 3 */}
          <div className="p-6 rounded-2xl border border-slate-900 bg-slate-950 hover:border-indigo-500/20 transition-all duration-300 group">
            <div className="w-12 h-12 rounded-xl bg-pink-500/10 text-pink-400 flex items-center justify-center group-hover:scale-110 transition-transform duration-300">
              <ImageIcon className="h-6 w-6" />
            </div>
            <h3 className="text-lg font-bold text-white mt-4">Featured Image AI</h3>
            <p className="mt-2 text-slate-400 text-sm leading-relaxed">
              Setiap artikel secara otomatis dibuatkan featured image representatif dan diupload langsung ke media library WordPress Anda. Bebas hak cipta.
            </p>
          </div>

          {/* Feature 4 */}
          <div className="p-6 rounded-2xl border border-slate-900 bg-slate-950 hover:border-indigo-500/20 transition-all duration-300 group">
            <div className="w-12 h-12 rounded-xl bg-emerald-500/10 text-emerald-400 flex items-center justify-center group-hover:scale-110 transition-transform duration-300">
              <Share2 className="h-6 w-6" />
            </div>
            <h3 className="text-lg font-bold text-white mt-4">Auto Share Sosial Media</h3>
            <p className="mt-2 text-slate-400 text-sm leading-relaxed">
              Hubungkan blog Anda ke Telegram Channel, Facebook Page, Twitter/X, & Threads. Artikel yang rilis akan otomatis di-post ke sana secara instan.
            </p>
          </div>

          {/* Feature 5 */}
          <div className="p-6 rounded-2xl border border-slate-900 bg-slate-950 hover:border-indigo-500/20 transition-all duration-300 group">
            <div className="w-12 h-12 rounded-xl bg-amber-500/10 text-amber-400 flex items-center justify-center group-hover:scale-110 transition-transform duration-300">
              <ListTodo className="h-6 w-6" />
            </div>
            <h3 className="text-lg font-bold text-white mt-4">Antrean & Perencana Konten</h3>
            <p className="mt-2 text-slate-400 text-sm leading-relaxed">
              Kelola ide artikel secara manual di halaman Queue. Tambah antrean postingan, ubah judul target, atau hapus antrean sesuai kebutuhan editorial Anda.
            </p>
          </div>

          {/* Feature 6 */}
          <div className="p-6 rounded-2xl border border-slate-900 bg-slate-950 hover:border-indigo-500/20 transition-all duration-300 group">
            <div className="w-12 h-12 rounded-xl bg-blue-500/10 text-blue-400 flex items-center justify-center group-hover:scale-110 transition-transform duration-300">
              <Globe className="h-6 w-6" />
            </div>
            <h3 className="text-lg font-bold text-white mt-4">Kustomisasi Model & Prompt</h3>
            <p className="mt-2 text-slate-400 text-sm leading-relaxed">
              Atur model teks dan gambar AI pilihan Anda. Anda juga dapat menentukan template instruksi (Prompt) tersendiri agar gaya bahasa sesuai brand Anda.
            </p>
          </div>
        </div>
      </section>

      {/* Workflow Section */}
      <section id="workflow" className="mx-auto max-w-7xl px-6 py-20 border-t border-slate-900 bg-slate-900/10">
        <div className="text-center max-w-3xl mx-auto mb-16">
          <h2 className="text-3xl md:text-4xl font-extrabold text-white">Alur Kerja Autopilot 3 Langkah Mudah</h2>
          <p className="mt-4 text-slate-400">
            Hanya butuh 5 menit untuk menghubungkan website Anda dan membiarkan sistem robot pintar kami mengambil alih.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-12 relative">
          {/* Step 1 */}
          <div className="flex flex-col items-center text-center relative z-10">
            <div className="w-16 h-16 rounded-2xl bg-indigo-500/10 text-indigo-400 flex items-center justify-center text-xl font-black border border-indigo-500/20 shadow-md">
              1
            </div>
            <h3 className="text-xl font-bold text-white mt-6">Hubungkan WordPress</h3>
            <p className="mt-3 text-slate-400 text-sm leading-relaxed max-w-xs">
              Masukkan detail website Anda beserta kredensial application password WordPress yang aman. Setup cepat & mudah.
            </p>
          </div>

          {/* Step 2 */}
          <div className="flex flex-col items-center text-center relative z-10">
            <div className="w-16 h-16 rounded-2xl bg-violet-500/10 text-violet-400 flex items-center justify-center text-xl font-black border border-violet-500/20 shadow-md">
              2
            </div>
            <h3 className="text-xl font-bold text-white mt-6">Tentukan Target & Tren</h3>
            <p className="mt-3 text-slate-400 text-sm leading-relaxed max-w-xs">
              Pilih kategori postingan Anda. AI akan mulai melakukan riset SEO harian berdasarkan tren pencarian real-time.
            </p>
          </div>

          {/* Step 3 */}
          <div className="flex flex-col items-center text-center relative z-10">
            <div className="w-16 h-16 rounded-2xl bg-pink-500/10 text-pink-400 flex items-center justify-center text-xl font-black border border-pink-500/20 shadow-md">
              3
            </div>
            <h3 className="text-xl font-bold text-white mt-6">Semua Berjalan Otomatis</h3>
            <p className="mt-3 text-slate-400 text-sm leading-relaxed max-w-xs">
              AI generate artikel + gambar, mempostingnya ke WP, dan menyebarkannya ke saluran sosial media Anda setiap hari.
            </p>
          </div>

          {/* Connector lines for desktop */}
          <div className="hidden lg:block absolute top-8 left-[16%] right-[16%] h-0.5 bg-gradient-to-r from-indigo-500/30 via-violet-500/30 to-pink-500/30 -z-0" />
        </div>
      </section>

      {/* Pricing Section */}
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
                  <span>Pilihan Model Gemini 2.5 Pro & Prompt Kustom</span>
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
                Pembayaran via Transfer Manual Bank. Konfirmasi instan ke Admin WhatsApp (Wa Confirmation).
              </span>
            </div>
          </div>
        </div>
      </section>

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
              Anda tinggal masuk ke halaman Billing di dalam dashboard, lalu pilih menu "Manual Transfer". Ikuti petunjuk nomor rekening yang disediakan dan klik tombol "Konfirmasi via WhatsApp" untuk mengirimkan bukti transfer secara instan ke admin.
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

          <div className="flex items-center gap-6">
            <span>&copy; {new Date().getFullYear()} AutoWP SaaS. All rights reserved.</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
