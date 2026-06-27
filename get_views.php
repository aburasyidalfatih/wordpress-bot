<?php
global $wpdb;
$results = $wpdb->get_results("
    SELECT p.post_title, CAST(m.meta_value AS UNSIGNED) as views 
    FROM {$wpdb->posts} p 
    JOIN {$wpdb->postmeta} m ON p.ID = m.post_id 
    WHERE p.post_type = 'post' AND p.post_status = 'publish' 
    AND m.meta_key = 'views'
    ORDER BY views DESC 
    LIMIT 50
");
if (empty($results)) {
    $results = $wpdb->get_results("
        SELECT p.post_title, CAST(m.meta_value AS UNSIGNED) as views 
        FROM {$wpdb->posts} p 
        JOIN {$wpdb->postmeta} m ON p.ID = m.post_id 
        WHERE p.post_type = 'post' AND p.post_status = 'publish' 
        AND m.meta_key = 'post_views_count'
        ORDER BY views DESC 
        LIMIT 50
    ");
}
if (empty($results)) {
    $results = $wpdb->get_results("
        SELECT p.post_title, CAST(m.meta_value AS UNSIGNED) as views 
        FROM {$wpdb->posts} p 
        JOIN {$wpdb->postmeta} m ON p.ID = m.post_id 
        WHERE p.post_type = 'post' AND p.post_status = 'publish' 
        AND m.meta_key = 'tie_views'
        ORDER BY views DESC 
        LIMIT 50
    ");
}
foreach ($results as $row) {
    echo $row->views . " - " . $row->post_title . "\n";
}
