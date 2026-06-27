<?php
// Update generic WordPress tagline
update_option('blogdescription', 'Pusat Referensi Manajemen Sekolah, SOP, dan Administrasi Pendidikan');

// Update Rank Math Homepage Title and Description
$rank_math_options = get_option('rank-math-options-titles');

if (is_array($rank_math_options)) {
    $rank_math_options['homepage_title'] = 'KelasMaster.id - Panduan Manajemen Sekolah & SOP Pendidikan Terlengkap';
    $rank_math_options['homepage_description'] = 'Portal referensi utama bagi Kepala Sekolah, Guru, dan Tenaga Kependidikan. Dapatkan ribuan panduan Kurikulum Merdeka, contoh SOP sekolah, hingga manajemen dana BOS.';
    
    update_option('rank-math-options-titles', $rank_math_options);
    echo "Rank Math Options updated.\n";
} else {
    echo "Rank Math Options not found, might be using a static homepage.\n";
}

echo "Tagline updated successfully.\n";
