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

  // Stage 6: Indexing Metadata
  index_status?: 'pending' | 'indexing' | 'indexed' | 'failed' | 'skipped' | null;
  index_error?: string | null;
  chunks_count?: number | null;
  indexed_at?: string | null;
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

// --- Stage 6: Chunking, Indexing, and Search Interfaces ---

export interface ChunkItem {
  id: string;
  document_id: string;
  chunk_index: number;
  text: string;
  embed_text: string;
  page_start: number;
  page_end: number;
  heading_path: string[];
  chunk_type: 'text' | 'table' | 'list' | 'mixed' | string;
  token_count: number;
  char_start?: number | null;
  char_end?: number | null;
  created_at: string;
}

export interface DocumentChunksResponse {
  document_id: string;
  total_chunks: number;
  chunks: ChunkItem[];
  index_status?: string | null;
  indexed_at?: string | null;
}

export interface ChunkDetailResponse {
  chunk: ChunkItem;
  prev_chunk?: ChunkItem | null;
  next_chunk?: ChunkItem | null;
}

export interface DocumentIndexResponse {
  document_id: string;
  index_status?: string | null;
  index_error?: string | null;
  chunks_total: number;
  chunks_embedded: number;
  indexed_at?: string | null;
  embedding_model?: string | null;
  embedding_dimension?: number | null;
}

export interface SearchResultItem {
  chunk_id: string;
  document_id: string;
  chunk_index: number;
  document_filename: string;
  text: string;
  page_start: number;
  page_end: number;
  heading_path: string[];
  chunk_type: string;
  token_count: number;
  score: number;
  vector_score?: number | null;
  vector_rank?: number | null;
  keyword_score?: number | null;
  keyword_rank?: number | null;
}

export interface SearchDebugResponse {
  query: string;
  mode: 'vector' | 'keyword' | 'hybrid' | string;
  limit: number;
  total_results: number;
  duration_ms: number;
  items: SearchResultItem[];
}

