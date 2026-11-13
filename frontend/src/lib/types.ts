export type TelegramStatus = "disconnected" | "code_sent" | "password_needed" | "connecting" | "connected" | "error";

export interface Status {
  telegram: { status: TelegramStatus; name: string | null; username: string | null; error: string | null };
  ai: { enabled: boolean; configured: boolean; draft_mode: boolean };
  bot: { configured: boolean; username: string | null };
  onboarding: { telegram: boolean; ai: boolean; pack: boolean; enabled: boolean; done: boolean };
  unread: number;
  drafts: number;
}

export interface Chat {
  id: string;
  name: string;
  username: string | null;
  has_photo: boolean;
  photo_version: number;
  ai_enabled: boolean;
  ai_paused: boolean;
  unread_count: number;
  last_message_at: string | null;
  last_message_text: string | null;
  last_message_sender: Sender | null;
  first_message_at: string | null;
  history_imported_at: string | null;
  has_draft: boolean;
  is_buyer: boolean;
}

export type Sender = "client" | "ai" | "owner" | "system";

export interface Message {
  id: number;
  chat_id: string;
  direction: "in" | "out";
  sender: Sender;
  kind: "text" | "media" | "payment_link" | "delivery";
  text: string;
  media_type: string | null;
  media_desc: string | null;
  has_media_file: boolean;
  status: "sent" | "draft" | "discarded" | "failed";
  created_at: string;
  pack_names: string[];
  imported: boolean;
}

export interface Sale {
  id: number;
  chat_id: string | null;
  client_name: string;
  client_has_photo: boolean;
  buyer_tg_id: string;
  pack_id: number | null;
  pack_name: string;
  stars: number;
  eur: number;
  paid_at: string;
  delivery_status: "pending" | "delivering" | "delivered" | "failed";
  delivery_error: string | null;
  delivered_at: string | null;
  refunded_at: string | null;
}

export interface ChatDetail extends Chat {
  customer: {
    total_stars: number;
    total_eur: number;
    purchases: Sale[];
    messages_count: number;
    first_message_at: string | null;
  };
}

export interface PackFile {
  id: number;
  filename: string;
  size: number;
  mime: string | null;
}

export interface Pack {
  id: number;
  name: string;
  description: string;
  price_stars: number;
  content_text: string;
  content_link: string;
  active: boolean;
  created_at: string;
  files: PackFile[];
  sales_count: number;
  sales_stars: number;
}

export interface Amount {
  stars: number;
  eur: number;
}

export interface Dashboard {
  rate: number;
  timezone: string;
  revenue: { today: Amount; d7: Amount; d30: Amount; total: Amount; prev_d7: Amount; prev_d30: Amount; yesterday: Amount };
  series: { date: string; stars: number; eur: number; count: number }[];
  by_pack: { pack_id: number | null; name: string; count: number; stars: number; eur: number }[];
  top_customers: { chat_id: number; name: string; has_photo: boolean; count: number; stars: number; eur: number }[];
  sales_count: number;
  refunded_count: number;
  conversations: number;
  buyers: number;
  conversion: number;
  recent_sales: Sale[];
}

export interface AIConfig {
  ai_base_url: string;
  ai_model: string;
  ai_api_key_set: boolean;
  ai_api_key_hint: string | null;
  ai_system_prompt: string;
  ai_never_deny_bot: boolean;
  ai_history_limit: number;
  ai_temperature: number;
}

export interface AppSettings {
  draft_mode: boolean;
  batch_delay_seconds: number;
  typing_min_seconds: number;
  typing_max_seconds: number;
  typing_chars_per_second: number;
  mark_as_read: boolean;
  rate_global_per_hour: number;
  rate_chat_per_hour: number;
  stars_eur_rate: number;
  delivery_intro: string;
  bot: { configured: boolean; username: string | null; token_hint: string | null };
  timezone: string;
}

export interface TelegramAccount {
  status: TelegramStatus;
  api_id: number | null;
  has_api_hash: boolean;
  phone: string | null;
  name: string | null;
  username: string | null;
  error: string | null;
}

export interface LogEntry {
  id: number;
  created_at: string;
  level: string;
  source: "site" | "telegram";
  message: string;
  details: string | null;
}
