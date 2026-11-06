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

export interface AttachedDocumentSummary {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes?: number;
  page_count?: number | null;
  mode?: string | null;
}

export interface MessageMeta {
  interrupted?: boolean;
  citations?: CitationItem[];
  usage?: TokenUsage;
  attached_documents?: AttachedDocumentSummary[];
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

  // Stage 5: Parsing Metadata
  parse_status?: 'pending' | 'parsing' | 'parsed' | 'failed' | 'skipped' | null;
  parse_error?: string | null;
  parser_name?: string | null;
  parser_version?: string | null;
  parse_started_at?: string | null;
  parse_finished_at?: string | null;
  pages_parsed?: number | null;
  parse_options?: Record<string, any> | null;
}

export interface DocumentParseSummary {
  total_warnings: number;
  low_text_pages: number[];
  garbled_pages: number[];
  pages_with_tables: number;
  pages_with_figures: number;
  total_characters: number;
}

export interface DocumentParseResponse {
  document_id: string;
  parse_status?: 'pending' | 'parsing' | 'parsed' | 'failed' | 'skipped' | null;
  parse_error?: string | null;
  parser_name?: string | null;
  parser_version?: string | null;
  parse_started_at?: string | null;
  parse_finished_at?: string | null;
  duration_seconds?: number | null;
  pages_parsed: number;
  total_pages?: number | null;
  parse_options?: Record<string, any> | null;
  warnings_summary?: DocumentParseSummary | null;
}

export interface DocumentPageSummary {
  id: string;
  page_no: number;
  char_count: number;
  has_table: boolean;
  has_figure: boolean;
  ocr_used?: boolean | null;
  warnings: string[];
}

export interface DocumentPagesListResponse {
  items: DocumentPageSummary[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

export interface DocumentPageDetail {
  id: string;
  document_id: string;
  page_no: number;
  markdown: string;
  plain_text: string;
  char_count: number;
  has_table: boolean;
  has_figure: boolean;
  ocr_used?: boolean | null;
  warnings: string[];
  created_at: string;
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
