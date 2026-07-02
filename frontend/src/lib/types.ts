export interface DashboardData {
  total_posts: number;
  total_categories: number;
  category_stats: CategoryStat[];
  recent_posts: RecentPost[];
  insights?: DashboardInsights;
  weekly_trend?: WeeklyTrend[];
}

export interface CategoryStat {
  name: string;
  count: number;
  percentage: number;
}

export interface RecentPost {
  title: string;
  category: string;
  created_at: string;
  post_url?: string;
  status?: string;
}

export interface DashboardInsights {
  recommendations: string[];
  best_time: string;
  top_category: string;
}

export interface WeeklyTrend {
  day: string;
  count: number;
}

export interface MonitorData {
  system_status: string;
  uptime: string;
  worker_status: string;
  queue_size: number;
  failed_jobs: number;
  total_completed: number;
  memory_usage?: string;
  cpu_usage?: string;
  last_post_time?: string;
  active_sites?: number;
  redis_status?: string;
  logs?: LogEntry[];
}

export interface LogEntry {
  timestamp: string;
  level: string;
  message: string;
}

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

export interface QueueItem {
  id: number;
  title: string;
  category: string;
  status: string;
  created_at: string;
  site_id?: number;
  position?: number;
}

export interface ResearchCategory {
  name: string;
  topic_count: number;
  last_research: string | null;
  topics: ResearchTopic[];
}

export interface ResearchTopic {
  id: number;
  topic: string;
  used: boolean;
  created_at: string;
}

export interface SiteConfig {
  id: number;
  site_name: string;
  wordpress_url: string;
  wordpress_username: string;
  is_active: boolean;
  auto_post: boolean;
  selected_categories: SiteCategory[];
  categories: SiteCategory[];
  language: string;
  post_interval: number;
  telegram_enabled: boolean;
  telegram_bot_token?: string;
  telegram_chat_id?: string;
  telegram_channel_id?: string;
  telegram_post_to_channel?: boolean;
  facebook_enabled: boolean;
  facebook_page_id?: string;
  facebook_access_token?: string;
  twitter_enabled: boolean;
  twitter_api_key?: string;
  twitter_api_secret?: string;
  twitter_access_token?: string;
  twitter_access_secret?: string;
  threads_enabled: boolean;
  threads_user_id?: string;
  threads_access_token?: string;
  article_prompt?: string;
  image_prompt?: string;
}

export interface SiteCategory {
  id: number;
  name: string;
  description?: string;
}

export interface UserProfile {
  email: string;
  name: string;
  credits: number;
  is_admin: boolean;
}

export interface BillingHistory {
  id: number;
  amount: number;
  credits: number;
  status: string;
  created_at: string;
  payment_method?: string;
}

export interface AdminStats {
  total_users: number;
  total_sites: number;
  total_posts: number;
  total_credits_used: number;
  active_users: number;
}

export interface AdminUser {
  id: number;
  email: string;
  name: string;
  credits: number;
  is_active: boolean;
  is_admin: boolean;
  sites_count: number;
  created_at: string;
}
