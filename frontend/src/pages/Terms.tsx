import { Link } from 'react-router-dom';
import { CONTACT_EMAIL, LegalPage } from '@/components/legal/LegalPage';

export default function Terms() {
  return (
    <LegalPage title="Syarat Layanan">
      <p>
        Dengan memakai AutoWP (autowp.web.id), Anda menyetujui syarat berikut.
      </p>

      <h2>Layanan</h2>
      <p>
        AutoWP membantu meriset topik, menulis artikel dengan AI, dan menerbitkannya ke website WordPress yang Anda
        hubungkan. Fitur dan kuota mengikuti paket dan kredit yang Anda miliki.
      </p>

      <h2>Tanggung jawab Anda</h2>
      <ul>
        <li>Anda hanya menghubungkan website dan akun Google Search Console yang Anda miliki atau berhak kelola.</li>
        <li>
          Anda bertanggung jawab atas konten yang diterbitkan di website Anda. Artikel dibuat dan diperiksa oleh sistem
          AI; periksa kembali informasi penting, terutama yang menyangkut keuangan, hukum, atau kesehatan.
        </li>
        <li>Anda tidak memakai AutoWP untuk konten yang melanggar hukum, spam, atau melanggar hak pihak lain.</li>
        <li>Anda menjaga kerahasiaan akun dan kredensial yang Anda masukkan.</li>
      </ul>

      <h2>Kredit dan pembayaran</h2>
      <p>
        Pembuatan artikel dan riset memakai kredit. Kredit untuk proses yang gagal dikembalikan otomatis sesuai
        ketentuan di halaman Tagihan.
      </p>

      <h2>Batasan tanggung jawab</h2>
      <p>
        AutoWP disediakan sebagaimana adanya. Kami berupaya menjaga layanan tetap berjalan dan akurat, tetapi tidak
        menjamin hasil tertentu, termasuk peringkat di mesin pencari.
      </p>

      <h2>Privasi</h2>
      <p>
        Penggunaan data dijelaskan di <Link to="/privacy">Kebijakan Privasi</Link>.
      </p>

      <h2>Kontak</h2>
      <p>
        Pertanyaan tentang syarat ini dapat dikirim ke <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
      </p>
    </LegalPage>
  );
}
