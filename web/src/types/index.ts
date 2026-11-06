export interface CitationItem {
  document_id: string;
  filename: string;
  page?: number | null;
  marker_text: string;
}

export interface TokenUsage {
  prompt_tokens?: number;
  candidates_tokens?: number;
  total_tokens?: number;
}

export interface MessageMeta {
  interrupted?: boolean;
  citations?: CitationItem[];
  usage?: TokenUsage;
  [key: string]: any;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant';
  content: string;
  meta?: MessageMeta | null;
  created_at: string;
}

export interface DocumentItem {
  id: string;
  conversation_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  sha256?: string;
  status: 'uploading' | 'processing' | 'ready' | 'failed';
  error?: string | null;
  page_count?: number | null;
  width?: number | null;
  height?: number | null;
  mode?: 'direct' | 'rag' | string | null;
  meta?: {
    lines?: number;
    characters?: number;
    gemini_file_name?: string;
    gemini_file_uri?: string;
    gemini_file_expires_at?: string;
    [key: string]: any;
  };
  created_at: string;
  updated_at: string;
  uploadProgress?: number; // client-side tracking before server response
}

export interface Conversation {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
  messages?: Message[];
  documents?: DocumentItem[];
}

export interface HealthStatus {
  api: 'ok' | 'error';
  db: 'ok' | 'error';
  pgvector: 'ok' | 'missing';
  gemini_key_configured: boolean;
}
