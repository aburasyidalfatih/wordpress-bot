<?php

$pages = [
    [
        'post_title'   => 'About Us',
        'post_content' => '<h2>Welcome to Family Budget Hub</h2>
<p>At <strong>Family Budget Hub</strong>, we believe that achieving financial freedom shouldn’t require a degree in finance. Our mission is to provide everyday families with simple, actionable, and proven strategies to take control of their money, pay off debt, and build generational wealth.</p>
<h3>Who We Are</h3>
<p>We are a dedicated team of personal finance enthusiasts, budgeting experts, and frugal living advocates. We understand the unique financial challenges that modern families face—from managing grocery bills and paying down student loans to saving for a child’s college education and planning for retirement.</p>
<h3>What We Do</h3>
<p>We break down complex financial concepts into easy-to-understand, bite-sized guides. Whether you are looking for zero-based budgeting templates, debt snowball strategies, or tips on beginner investing (like ETFs and Roth IRAs), we have you covered.</p>
<p>Join us on our journey to financial independence, and let’s build a secure future for your family together!</p>',
        'post_status'  => 'publish',
        'post_type'    => 'page',
    ],
    [
        'post_title'   => 'Contact Us',
        'post_content' => '<h2>Get in Touch</h2>
<p>We would love to hear from you! Whether you have a question about one of our budgeting strategies, need advice on managing your family finances, or simply want to share your debt-free journey with us, our inbox is always open.</p>
<h3>How to Reach Us</h3>
<p>For general inquiries, feedback, or partnership opportunities, please reach out to us via email:</p>
<p>📧 <strong>Email:</strong> hello@familybudgethub.com</p>
<p>We strive to respond to all inquiries within 24-48 business hours. Thank you for being a valued reader of <strong>Family Budget Hub</strong>!</p>',
        'post_status'  => 'publish',
        'post_type'    => 'page',
    ],
    [
        'post_title'   => 'Disclaimer',
        'post_content' => '<h2>Financial Disclaimer</h2>
<p>The information provided on <strong>Family Budget Hub</strong> (the "Website") is for educational and informational purposes only. It does not constitute financial, investment, legal, or tax advice.</p>
<h3>No Professional Advice</h3>
<p>The content published on this Website is based on the personal experiences, research, and opinions of our writers. We are not certified financial planners, licensed investment advisors, or CPAs. You should not rely solely on the information provided on this Website to make financial decisions. Always consult with a qualified financial professional before making any significant monetary or investment choices.</p>
<h3>Accuracy of Information</h3>
<p>While we strive to keep the information on this Website accurate and up-to-date, the financial landscape changes rapidly. We make no warranties or representations regarding the accuracy, completeness, or reliability of any information found here. Your use of the Website and your reliance on any information on the Website is solely at your own risk.</p>
<h3>Affiliate Disclosure</h3>
<p>Some of the links on this Website may be affiliate links. This means that if you click on the link and make a purchase, we may receive a small commission at no extra cost to you. We only recommend products and services that we genuinely believe will add value to our readers.</p>',
        'post_status'  => 'publish',
        'post_type'    => 'page',
    ],
    [
        'post_title'   => 'Terms and Conditions',
        'post_content' => '<h2>Terms of Use</h2>
<p>Welcome to <strong>Family Budget Hub</strong>. By accessing or using our Website, you agree to be bound by these Terms and Conditions. If you do not agree with any part of these terms, please do not use our Website.</p>
<h3>Intellectual Property</h3>
<p>All content on this Website, including text, graphics, logos, images, and software, is the property of Family Budget Hub and is protected by international copyright and intellectual property laws. You may not reproduce, distribute, or modify any content without our prior written consent.</p>
<h3>User Conduct</h3>
<p>When interacting with our Website (e.g., leaving comments), you agree not to post any unlawful, defamatory, abusive, or spam material. We reserve the right to remove any content that violates these guidelines without notice.</p>
<h3>Limitation of Liability</h3>
<p>In no event shall Family Budget Hub or its team be liable for any direct, indirect, incidental, consequential, or punitive damages arising out of your access to, or use of, the Website. We do not guarantee that the Website will be error-free or uninterrupted.</p>
<h3>Changes to These Terms</h3>
<p>We reserve the right to modify these Terms and Conditions at any time. Any changes will be effective immediately upon posting on this page. Your continued use of the Website after any modifications indicates your acceptance of the updated terms.</p>',
        'post_status'  => 'publish',
        'post_type'    => 'page',
    ]
];

foreach ($pages as $page) {
    // Check if page already exists to prevent duplicates
    $existing = get_page_by_title($page['post_title'], OBJECT, 'page');
    if (!$existing) {
        wp_insert_post($page);
        echo "Created page: " . $page['post_title'] . "\n";
    } else {
        echo "Page already exists: " . $page['post_title'] . "\n";
    }
}
