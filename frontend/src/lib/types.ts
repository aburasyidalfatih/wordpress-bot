// Shapes of the JSON returned by the backend API.

// ---------------------------------------------------------------------------
// Websites
// ---------------------------------------------------------------------------

export interface SiteCategory {
  id: number;
  name: string;
  description?: string;
  count?: number;
}

export interface WordPressSite {
  id: number;
  site_name: string;
  wordpress_url: string;
  wordpress_username: string;
  is_active: boolean;

  schedule_hours: string;
  timezone?: string;
  language?: string;
  auto_post: boolean;
  categories: SiteCategory[];
  selected_categories: SiteCategory[];
  telegram_enabled: boolean;
  telegram_bot_token: string;
  telegram_chat_id: string;
  facebook_enabled: boolean;
  twitter_enabled: boolean;
  threads_enabled: boolean;

  article_prompt: string | null;
  image_prompt: string | null;
  wordpress_password?: string;
  has_wordpress_password?: boolean;
  telegram_post_to_channel?: boolean;
  telegram_channel_id?: string;
  has_telegram_bot_token?: boolean;
  facebook_page_id?: string;
  facebook_access_token?: string;
  has_facebook_access_token?: boolean;
  pinterest_enabled?: boolean;
  pinterest_board_id?: string;
  pinterest_access_token?: string;
  has_pinterest_access_token?: boolean;
  twitter_api_key?: string;
  twitter_api_secret?: string;
  twitter_access_token?: string;
  twitter_access_secret?: string;
  has_twitter_api_key?: boolean;
  has_twitter_api_secret?: boolean;
  has_twitter_access_token?: boolean;
  has_twitter_access_secret?: boolean;
  threads_user_id?: string;
  threads_access_token?: string;
  has_threads_access_token?: boolean;
  gsc_connected?: boolean;
  gsc_client_id?: string;
  gsc_client_secret?: string;
  has_gsc_client_secret?: boolean;
  gsc_property_url?: string | null;
  gsc_permission_level?: string | null;
  gsc_connected_at?: string | null;
  gsc_last_synced_at?: string | null;
  gsc_last_error?: string | null;
}

/** A website being created (no id yet) or edited in the site form. */
export type SiteDraft = Partial<WordPressSite>;

export interface GscProperty {
  site_url: string;
  permission_level?: string;
}

// ---------------------------------------------------------------------------
// User profile
// ---------------------------------------------------------------------------

export interface UserProfile {
  name?: string;
  email?: string;
  role?: string;
  tier?: string;
  credits?: number;
}

interface AuthUser {
  role?: string;
}

/** Response of /api/login and /api/auth/google. */
export interface LoginResponse {
  success: boolean;
  token?: string;
  user?: AuthUser;
  error?: string;
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

interface DashboardRecommendation {
  type: string;
  category: string;
  action: string;
  reason: string;
}

export interface DashboardInsightsData {
  status: string;
  message?: string;
  recommendations?: DashboardRecommendation[];
}

export interface DashboardLogEntry {
  title: string;
  category: string;
  timestamp: string;
  success: boolean | 'pending';
  result?: string;
}

export interface CategoryPerformance {
  category: string;
  total_posts: number;
  total_views: number;
  total_comments: number;
  avg_engagement: number;
}

export interface DashboardApiResponse {
  stats?: {
    total_posts: number;
    success_rate: number;
    failed_posts: number;
  };
  next_post_time?: string;
  logs?: DashboardLogEntry[];
  insights?: DashboardInsightsData;
  performance?: CategoryPerformance[];
}

// ---------------------------------------------------------------------------
// System monitor
// ---------------------------------------------------------------------------

interface MonitorSystemInfo {
  cpu_percent: number;
  memory_percent: number;
  disk_percent: number;
  uptime: string;
}

export interface MonitorServiceInfo {
  // null means the heartbeat could not be read (e.g. Redis unreachable), which is
  // different from the scheduler being confirmed down.
  scheduler_running: boolean | null;
  scheduler_last_heartbeat?: string | null;
  scheduler_detail?: string | null;
  scheduler_jobs: number | null;
  database_size?: number | null;
  log_size: number;
}

export interface MonitorApiResponse {
  system_info?: MonitorSystemInfo;
  service_info?: MonitorServiceInfo;
  recent_errors?: string[];
}

// ---------------------------------------------------------------------------
// Prompts
// ---------------------------------------------------------------------------

export interface PromptsData {
  article_prompt: string;
  image_prompt: string;
  default_article_prompt: string;
  default_image_prompt: string;
  config?: {
    article_prompt?: string;
    image_prompt?: string;
  };
}

// ---------------------------------------------------------------------------
// Queue
// ---------------------------------------------------------------------------

export interface QueueItem {
  id: number;
  title: string;
  category: string;
  status: string;
  target_keywords?: string;
  created_at?: string;
  post_url?: string;
}

export interface HistoryItem {
  id: number;
  title: string;
  category: string;
  success: boolean;
  image_failed: boolean;
  timestamp: string;
  result: string;
  post_url?: string;
}

// ---------------------------------------------------------------------------
// Research
// ---------------------------------------------------------------------------

export interface SearchOpportunity {
  type: 'quick_win' | 'low_ctr' | 'declining';
  query: string;
  page: string;
  clicks: number;
  impressions: number;
  ctr: number;
  position: number;
  click_change: number;
  position_change?: number | null;
  opportunity_score: number;
  rationale: string;
  /** Recommended response, e.g. 'new_article', 'rewrite_meta' or 'refresh_content'. */
  action?: string;
  /** Human-readable (Indonesian) description of `action`. */
  action_label?: string;
  /** Search intent of the query, e.g. 'informational' or 'commercial'. */
  intent?: string;
}

export interface SearchConsoleSummary {
  connected: boolean;
  property_url?: string | null;
  last_synced_at?: string | null;
  opportunities: SearchOpportunity[];
  /** Why the opportunities could not be loaded (sync failure, expired token...). */
  error?: string | null;
}

interface ResearchKeyword {
  keyword: string;
  impressions: number | null;
  has_demand_data: boolean;
  intent?: string;
}

type ConfidenceLevel = 'high' | 'medium' | 'low' | 'insufficient' | 'unknown';

export interface ResearchStats {
  created_at: string;
  trend_score: number;
  // The API annotates keywords with Search Console demand. Older responses (and
  // research saved before that change) may still return plain strings.
  keywords: (ResearchKeyword | string)[];
  quality_score: number;
  confidence_level: ConfidenceLevel;
  is_fallback: boolean;
  /** Writer evidence that is missing or template-only, in Indonesian. Older APIs omit it. */
  fallback_warnings?: string[];
  /** Optional sources (social, YouTube, ...) that were unavailable; information only. */
  missing_optional_sources?: string[];
  is_stale: boolean;
  age_hours: number | null;
  /** False when the research is too weak to generate titles from. Older APIs omit it. */
  eligible_for_titles?: boolean;
  /** Why titles cannot be generated from this research; null when eligible. */
  title_block_reason?: string | null;
  long_tail_keywords: string[];
  semantic_context: string;
  news_insights: { title: string; source?: string; url?: string; published_at?: string }[];
  /** Government pages for the category (Claude web research). Older APIs omit it. */
  official_sources?: { title: string; url: string; passages?: string[] }[];
  source_metadata: Record<string, {
    status?: string; count?: number; checked_at?: string; reason?: string;
    /** Google Trends: the shorter head term the score was measured for. */
    trend_term?: string;
  }>;
  social_insights: ({ text: string; url?: string; provider?: string } | string)[];
  competitor_outlines: {
    title: string;
    url: string;
    headers: string[];
  }[];
  youtube_insights: {
    title: string;
    snippets: string;
    url?: string;
    transcript_available?: boolean;
  }[];
}

export interface ResearchDataResponse {
  categories: SiteCategory[];
  research_data: Record<string, ResearchStats>;
  search_console?: SearchConsoleSummary;
}

/** Outcome of a finished research job (null for jobs from older backends). */
export interface ResearchJobResult {
  successful_categories?: number;
  failed_categories?: number;
  refunded_credits?: number;
  skipped?: boolean;
  reason?: string | null;
}

/** GET /api/job-status/<id> */
export interface JobStatusResponse {
  success: boolean;
  status: string;
  progress: number;
  message: string;
  result?: ResearchJobResult | null;
  /** The job's RQ timeout (seconds), when the backend reports it. */
  timeout_seconds?: number | null;
  error?: string;
}

// ---------------------------------------------------------------------------
// Billing
// ---------------------------------------------------------------------------

export interface BankDetails {
  bank_name: string;
  account_number: string;
  account_holder: string;
  whatsapp_number?: string;
}

export interface InvoiceData {
  invoice_id: string;
  payment_method: string;
  is_mock?: boolean;
  amount?: number;
  amount_usd?: number;
  checkout_url?: string | null;
  tripay_data?: {
    reference?: string;
    pay_code?: string;
    qr_string?: string;
    payment_name?: string;
    amount?: number;
    status?: string;
  };
  paypal_order_id?: string;
  paypal_approve_url?: string | null;
  bank_details?: BankDetails;
}

export interface BillingProfile {
  credits?: number;
  tier?: string;
}

export interface BillingHistoryItem {
  id: number;
  invoice_id: string;
  created_at: string;
  payment_method: string;
  credits_purchased: number;
  amount: number;
  status: string;
  receipt_url?: string;
  bank_details?: BankDetails;
}

export type PaymentMethod = 'manual' | 'tripay' | 'paypal' | '';

export interface PaymentMethodsEnabled {
  manual: boolean;
  tripay: boolean;
  paypal: boolean;
}

// ---------------------------------------------------------------------------
// Admin
// ---------------------------------------------------------------------------

export interface AdminStats {
  total_users?: number;
  total_pro?: number;
  total_earnings_idr?: number;
  total_credits_purchased?: number;
  queue_count?: number;
  total_articles?: number;
}

export interface AdminUser {
  id: number;
  name: string;
  email: string;
  role: string;
  tier: string;
  credits: number;
  is_active: boolean;
}

export interface PendingPayment {
  id: number;
  invoice_id: string;
  created_at: string;
  user_name: string;
  user_email: string;
  credits_purchased: number;
  amount: number;
  receipt_url?: string;
}

export type AiTextProvider = 'gemini' | 'anthropic' | 'openai';
export type AiImageProvider = 'gemini' | 'openai';

export interface AdminConfig {
  PAYMENT_USD_RATE?: number;
  PAYMENT_TRIPAY_ENABLED?: boolean;
  TRIPAY_MERCHANT_CODE?: string;
  TRIPAY_API_URL?: string;
  TRIPAY_API_KEY?: string;
  TRIPAY_PRIVATE_KEY?: string;
  has_TRIPAY_API_KEY?: boolean;
  has_TRIPAY_PRIVATE_KEY?: boolean;
  PAYMENT_PAYPAL_ENABLED?: boolean;
  PAYPAL_API_URL?: string;
  PAYPAL_CLIENT_ID?: string;
  PAYPAL_SECRET?: string;
  has_PAYPAL_SECRET?: boolean;
  PAYMENT_MANUAL_ENABLED?: boolean;
  MANUAL_BANK_NAME?: string;
  MANUAL_BANK_HOLDER?: string;
  MANUAL_BANK_ACCOUNT?: string;
  ADMIN_WHATSAPP?: string;
  ai_text_provider?: AiTextProvider;
  ai_image_provider?: AiImageProvider;
  gemini_api_key?: string;
  has_gemini_api_key?: boolean;
  gemini_model?: string;
  gemini_image_model?: string;
  anthropic_api_key?: string;
  has_anthropic_api_key?: boolean;
  anthropic_model?: string;
  openai_api_key?: string;
  has_openai_api_key?: boolean;
  openai_model?: string;
  openai_image_model?: string;
  GOOGLE_CLIENT_ID?: string;
  GOOGLE_CLIENT_SECRET?: string;
  has_GOOGLE_CLIENT_SECRET?: boolean;
  SMTP_HOST?: string;
  SMTP_PORT?: number;
  SMTP_USER?: string;
  SMTP_PASSWORD?: string;
  has_SMTP_PASSWORD?: boolean;
  SMTP_SENDER_EMAIL?: string;
  STARSENDER_API_KEY?: string;
  has_STARSENDER_API_KEY?: boolean;
  STARSENDER_DEVICE_ID?: string;
}
