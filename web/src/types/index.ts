export interface Message {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant';
  content: string;
  meta?: {
    interrupted?: boolean;
    citations?: any[];
    [key: string]: any;
  } | null;
  created_at: string;
}

export interface Conversation {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
  messages?: Message[];
}

export interface HealthStatus {
  api: 'ok' | 'error';
  db: 'ok' | 'error';
  pgvector: 'ok' | 'missing';
  gemini_key_configured: boolean;
}

