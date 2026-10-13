import { Search, Image as ImageIcon, Share2, ListTodo, Sparkles, Globe } from 'lucide-react';

/** Grid of the six main features. */
export function FeaturesSection() {
  return (
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
          <h3 className="text-lg font-bold text-white mt-4">Intelligence Hub & Riset SEO</h3>
          <p className="mt-2 text-slate-400 text-sm leading-relaxed">
            Sistem secara otomatis memindai kompetitor, mencatat tren kata kunci, mengekstrak pertanyaan pengguna, dan mengumpulkan video YouTube terpopuler untuk riset topik mendalam.
          </p>
        </div>

        {/* Feature 2 */}
        <div className="p-6 rounded-2xl border border-slate-900 bg-slate-950 hover:border-indigo-500/20 transition-all duration-300 group">
          <div className="w-12 h-12 rounded-xl bg-violet-500/10 text-violet-400 flex items-center justify-center group-hover:scale-110 transition-transform duration-300">
            <Sparkles className="h-6 w-6" />
          </div>
          <h3 className="text-lg font-bold text-white mt-4">Penulis AI & Multi-Bahasa</h3>
          <p className="mt-2 text-slate-400 text-sm leading-relaxed">
            Generate puluhan judul massal dan tulis konten SEO otomatis menggunakan model AI Gemini. Sistem otomatis menyesuaikan gaya penulisan untuk target audiens Lokal (Indonesia) maupun Global (Inggris).
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
          <h3 className="text-lg font-bold text-white mt-4">Antrean, Acak Judul & Riwayat</h3>
          <p className="mt-2 text-slate-400 text-sm leading-relaxed">
            Kelola ide artikel di antrean, gunakan fitur acak (shuffle) agar kategori postingan bervariasi, prioritas auto-posting, serta pantau semua riwayat artikel yang sukses rilis.
          </p>
        </div>

        {/* Feature 6 */}
        <div className="p-6 rounded-2xl border border-slate-900 bg-slate-950 hover:border-indigo-500/20 transition-all duration-300 group">
          <div className="w-12 h-12 rounded-xl bg-blue-500/10 text-blue-400 flex items-center justify-center group-hover:scale-110 transition-transform duration-300">
            <Globe className="h-6 w-6" />
          </div>
          <h3 className="text-lg font-bold text-white mt-4">Multi-Situs & Kustomisasi Prompt</h3>
          <p className="mt-2 text-slate-400 text-sm leading-relaxed">
            Kelola berbagai situs WordPress sekaligus dari 1 dashboard terpusat tanpa harus login manual berulang kali. Anda juga bebas menentukan instruksi (Prompt) AI sesuai karakter brand Anda.
          </p>
        </div>
      </div>
    </section>
  );
}
