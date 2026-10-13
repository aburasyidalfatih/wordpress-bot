/** The three-step "how it works" section. */
export function WorkflowSection() {
  return (
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
  );
}
