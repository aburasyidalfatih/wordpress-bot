import { CONTACT_EMAIL, LegalPage } from '@/components/legal/LegalPage';

export default function Privacy() {
  return (
    <LegalPage title="Kebijakan Privasi">
      <p>
        AutoWP (autowp.web.id) adalah layanan untuk menulis dan menerbitkan artikel ke website WordPress milik
        pengguna secara otomatis. Halaman ini menjelaskan data apa yang kami kumpulkan, untuk apa, dan bagaimana
        Anda mengendalikannya.
      </p>

      <h2>Data yang kami kumpulkan</h2>
      <ul>
        <li><strong>Data akun:</strong> nama dan alamat email yang Anda pakai untuk masuk.</li>
        <li>
          <strong>Data website:</strong> alamat website WordPress, nama pengguna, dan application password yang Anda
          masukkan. Kredensial disimpan terenkripsi dan hanya dipakai untuk menerbitkan dan memperbarui artikel di
          website Anda.
        </li>
        <li><strong>Pengaturan konten:</strong> kategori, prompt, antrean topik, dan riwayat artikel yang dibuat.</li>
        <li>
          <strong>Data Google Search Console</strong>, hanya bila Anda menghubungkannya (lihat bagian berikut).
        </li>
      </ul>

      <h2>Penggunaan data Google</h2>
      <p>
        Bila Anda menghubungkan Google Search Console, AutoWP meminta akses <strong>hanya-baca</strong> (scope{' '}
        <code>https://www.googleapis.com/auth/webmasters.readonly</code>) ke properti website Anda. Kami membaca
        kueri pencarian, halaman, klik, impresi, dan posisi rata-rata untuk menampilkan performa website di dasbor
        dan memilih topik artikel berikutnya.
      </p>
      <ul>
        <li>Data ini hanya dipakai untuk fitur tersebut dan hanya ditampilkan kepada Anda.</li>
        <li>Kami tidak menjual data Google Anda, tidak memakainya untuk iklan, dan tidak membagikannya kepada pihak lain.</li>
        <li>Kami tidak memakai data Google Anda untuk melatih model AI.</li>
        <li>
          Penggunaan dan pemindahan informasi yang diterima dari Google API oleh AutoWP mematuhi{' '}
          <a href="https://developers.google.com/terms/api-services-user-data-policy" target="_blank" rel="noopener noreferrer">
            Kebijakan Data Pengguna Layanan Google API
          </a>
          , termasuk persyaratan Limited Use.
        </li>
        <li>
          Anda dapat memutus akses kapan saja dari halaman pengaturan website di AutoWP atau dari{' '}
          <a href="https://myaccount.google.com/permissions" target="_blank" rel="noopener noreferrer">
            pengaturan izin akun Google
          </a>
          . Setelah diputus, data Search Console yang tersimpan untuk website itu dihapus.
        </li>
      </ul>

      <h2>Pemrosesan oleh penyedia AI</h2>
      <p>
        Untuk menulis artikel, topik dan bahan riset dikirim ke penyedia AI yang dipilih (Google Gemini, Anthropic
        Claude, atau OpenAI). Data Search Console dan kredensial website tidak dikirim ke penyedia AI selain kueri
        pencarian yang relevan dengan topik artikel.
      </p>

      <h2>Penyimpanan dan keamanan</h2>
      <p>
        Data disimpan di server kami dan dilindungi dengan enkripsi untuk kredensial serta akses terbatas. Data
        disimpan selama akun Anda aktif. Anda dapat meminta penghapusan akun dan data kapan saja.
      </p>

      <h2>Hak Anda</h2>
      <p>
        Sesuai Undang-Undang Nomor 27 Tahun 2022 tentang Pelindungan Data Pribadi, Anda dapat meminta akses,
        perbaikan, atau penghapusan data pribadi Anda dengan menghubungi kami.
      </p>

      <h2>Kontak</h2>
      <p>
        Pertanyaan tentang kebijakan ini dapat dikirim ke <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
      </p>
    </LegalPage>
  );
}
