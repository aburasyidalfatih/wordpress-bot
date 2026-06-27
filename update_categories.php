<?php
$updates = [
    38 => 'Kumpulan panduan dan contoh SOP Sekolah terlengkap. Temukan berbagai Standar Operasional Prosedur (SOP) praktis untuk administrasi TU, SOP guru mengajar, SOP PPDB, SOP Ekstrakurikuler, hingga SOP penanganan kasus di sekolah dan madrasah.',
    35 => 'Panduan tata kelola Manajemen Keuangan Sekolah yang transparan dan akuntabel. Tips penyusunan RKAS, pengelolaan Dana BOS yang aman dari temuan Inspektorat, strategi pelaporan keuangan, serta manajemen dana Komite Sekolah dan Yayasan.',
    39 => 'Referensi utama implementasi Kurikulum Merdeka di sekolah. Dapatkan panduan menyusun Modul Ajar, penyelarasan CP dan ATP, pelaksanaan Projek P5, pengisian E-Kinerja PMM, hingga strategi adaptasi kurikulum untuk Kepala Sekolah dan Guru.',
    41 => 'Panduan langkah demi langkah mengurus Izin Operasional Sekolah, pendirian Yayasan Pendidikan, hingga persyaratan legalitas akreditasi BAN-PDM. Solusi birokrasi tanpa ribet bagi pengelola sekolah swasta maupun negeri.',
    1 => 'Inspirasi dan panduan Kepemimpinan Kepala Sekolah (Principalship) dan Yayasan di era digital. Membahas strategi manajemen konflik, supervisi akademik guru, kolaborasi sekolah, hingga cara membangun visi sekolah yang berdaya saing tinggi.',
    36 => 'Trik dan strategi Digital Marketing Sekolah untuk memenangkan pendaftaran siswa baru. Panduan optimasi kampanye PPDB Online, branding yayasan di media sosial, pembuatan brosur sekolah, dan pemanfaatan website untuk menjaring murid.',
    43 => 'Panduan tata kelola Pesantren Modern dan Boarding School. Membahas tuntas manajemen asrama, penyusunan tata tertib santri/siswa, manajemen katering sekolah, hingga pengawasan kedisiplinan 24 jam.',
    44 => 'Ide bisnis dan pengelolaan Unit Usaha Sekolah (Koperasi Sekolah). Strategi mewujudkan kemandirian finansial Yayasan Pendidikan melalui pengembangan bisnis edukasi, sewa aset, dan kewirausahaan siswa.'
];

foreach ($updates as $term_id => $description) {
    wp_update_term($term_id, 'category', array(
        'description' => $description
    ));
}
echo "Category descriptions updated successfully.\n";
