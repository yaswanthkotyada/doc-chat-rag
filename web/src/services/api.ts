import {
  Conversation,
  DocumentItem,
  HealthStatus,
  CitationItem,
  TokenUsage,
  DocumentParseResponse,
  DocumentPagesListResponse,
  DocumentPageDetail,
  DocumentChunksResponse,
  ChunkDetailResponse,
  DocumentIndexResponse,
  SearchDebugResponse,
  AgentStepTrace,
  RoutingPlan,
} from '../types';

export const API_BASE_URL = (import.meta as any).env?.VITE_API_URL || 'http://localhost:8000';

export async function fetchHealth(): Promise<HealthStatus> {
  const res = await fetch(`${API_BASE_URL}/api/health`);
  return res.json();
}

export async function fetchConversations(): Promise<Conversation[]> {
  const res = await fetch(`${API_BASE_URL}/api/conversations`);
  if (!res.ok) {
    throw new Error('Failed to fetch conversations');
  }
  return res.json();
}

export async function createConversation(title?: string): Promise<{ id: string; title: string | null }> {
  const res = await fetch(`${API_BASE_URL}/api/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(title ? { title } : {}),
  });
  if (!res.ok) {
    throw new Error('Failed to create conversation');
  }
  return res.json();
}

export async function fetchConversation(id: string): Promise<Conversation> {
  const res = await fetch(`${API_BASE_URL}/api/conversations/${id}`);
  if (!res.ok) {
    throw new Error('Failed to fetch conversation details');
  }
  return res.json();
}

export async function deleteConversation(id: string): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/api/conversations/${id}`, {
    method: 'DELETE',
  });
  if (!res.ok && res.status !== 404) {
    throw new Error('Failed to delete conversation');
  }
}

// --- Document API functions (Stage 3) ---

export function getDocumentFileUrl(documentId: string): string {
  return `${API_BASE_URL}/api/documents/${documentId}/file`;
}

export async function fetchDocuments(conversationId: string): Promise<DocumentItem[]> {
  const res = await fetch(`${API_BASE_URL}/api/conversations/${conversationId}/documents`);
  if (!res.ok) {
    throw new Error('Failed to fetch conversation documents');
  }
  return res.json();
}

export async function fetchDocument(documentId: string): Promise<DocumentItem> {
  const res = await fetch(`${API_BASE_URL}/api/documents/${documentId}`);
  if (!res.ok) {
    throw new Error('Failed to fetch document status');
  }
  return res.json();
}

export async function deleteDocument(documentId: string): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/api/documents/${documentId}`, {
    method: 'DELETE',
  });
  if (!res.ok && res.status !== 404) {
    throw new Error('Failed to delete document');
  }
}

// --- Document Parsing API functions (Stage 5) ---

export function getDocumentParsedMdUrl(documentId: string): string {
  return `${API_BASE_URL}/api/documents/${documentId}/parsed.md`;
}

export async function fetchDocumentParse(documentId: string): Promise<DocumentParseResponse> {
  const res = await fetch(`${API_BASE_URL}/api/documents/${documentId}/parse`);
  if (!res.ok) {
    throw new Error('Failed to fetch document parse status');
  }
  return res.json();
}

export async function retryDocumentParse(documentId: string): Promise<DocumentParseResponse> {
  const res = await fetch(`${API_BASE_URL}/api/documents/${documentId}/parse/retry`, {
    method: 'POST',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Failed to retry document parsing');
  }
  return res.json();
}

export async function fetchDocumentPages(
  documentId: string,
  page = 1,
  limit = 50
): Promise<DocumentPagesListResponse> {
  const res = await fetch(`${API_BASE_URL}/api/documents/${documentId}/pages?page=${page}&limit=${limit}`);
  if (!res.ok) {
    throw new Error('Failed to fetch document pages');
  }
  return res.json();
}

export async function fetchDocumentPageDetail(
  documentId: string,
  pageNo: number
): Promise<DocumentPageDetail> {
  const res = await fetch(`${API_BASE_URL}/api/documents/${documentId}/pages/${pageNo}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch page ${pageNo} details`);
  }
  return res.json();
}

export function uploadDocuments(
  conversationId: string,
  files: File[],
  onProgress?: (percent: number) => void
): Promise<DocumentItem[]> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const formData = new FormData();

    for (const file of files) {
      formData.append('files', file);
    }

    xhr.open('POST', `${API_BASE_URL}/api/conversations/${conversationId}/documents`);

    if (xhr.upload && onProgress) {
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          const percent = Math.round((event.loaded / event.total) * 100);
          onProgress(percent);
        }
      };
    }

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const data = JSON.parse(xhr.responseText);
          resolve(data);
        } catch {
          reject(new Error('Invalid response from server'));
        }
      } else {
        try {
          const errData = JSON.parse(xhr.responseText);
          const msg = typeof errData.detail === 'string'
            ? errData.detail
            : errData.detail?.[0]?.msg || 'Upload failed';
          reject(new Error(msg));
        } catch {
          reject(new Error(xhr.statusText || 'Upload failed'));
        }
      }
    };

    xhr.onerror = () => reject(new Error('Network error during upload'));
    xhr.send(formData);
  });
}

// --- Chat Streaming (Stage 2) ---

export async function streamChatMessage({
  conversationId,
  message,
  documentIds,
  onToken,
  onPlan,
  onToolCall,
  onToolResult,
  onDone,
  onError,
  signal,
}: {
  conversationId: string;
  message: string;
  documentIds?: string[];
  onToken: (chunk: string) => void;
  onPlan?: (plan: RoutingPlan) => void;
  onToolCall?: (data: { step: number; tool: string; arguments: any }) => void;
  onToolResult?: (data: { step: number; tool: string; result_count: number; pages: number[]; duration_ms: number }) => void;
  onDone: (
    messageId: string,
    citations?: CitationItem[],
    usage?: TokenUsage,
    agentTrace?: AgentStepTrace[],
    routingPlan?: RoutingPlan,
    limitHit?: boolean
  ) => void;
  onError: (error: string) => void;
  signal?: AbortSignal;
}): Promise<void> {
  try {
    const bodyPayload: any = { conversation_id: conversationId, message };
    if (documentIds !== undefined) {
      bodyPayload.document_ids = documentIds;
    }

    const response = await fetch(`${API_BASE_URL}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(bodyPayload),
      signal,
    });

    if (!response.ok) {
      let errorMsg = 'Failed to send message';
      try {
        const errorData = await response.json();
        if (errorData.detail) {
          errorMsg = typeof errorData.detail === 'string'
            ? errorData.detail
            : errorData.detail[0]?.msg || JSON.stringify(errorData.detail);
        }
      } catch {
        errorMsg = response.statusText || errorMsg;
      }
      onError(errorMsg);
      return;
    }

    if (!response.body) {
      onError('Response body is empty.');
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split('\n\n');
      buffer = blocks.pop() || '';

      for (const block of blocks) {
        if (!block.trim()) continue;

        let eventType = 'message';
        let dataStr = '';

        const lines = block.split('\n');
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith('data: ')) {
            dataStr = line.slice(6);
          }
        }

        if (eventType === 'plan') {
          try {
            const parsed = JSON.parse(dataStr);
            if (onPlan) onPlan(parsed);
          } catch {
            // Ignore parse errors
          }
        } else if (eventType === 'tool_call') {
          try {
            const parsed = JSON.parse(dataStr);
            if (onToolCall) onToolCall(parsed);
          } catch {
            // Ignore parse errors
          }
        } else if (eventType === 'tool_result') {
          try {
            const parsed = JSON.parse(dataStr);
            if (onToolResult) onToolResult(parsed);
          } catch {
            // Ignore parse errors
          }
        } else if (eventType === 'token') {
          try {
            const parsed = JSON.parse(dataStr);
            onToken(parsed.text !== undefined ? parsed.text : dataStr);
          } catch {
            onToken(dataStr);
          }
        } else if (eventType === 'done') {
          try {
            const parsed = JSON.parse(dataStr);
            onDone(
              parsed.message_id || '',
              parsed.citations,
              parsed.usage,
              parsed.agent_trace,
              parsed.routing_plan,
              parsed.limit_hit
            );
          } catch {
            onDone('');
          }
        } else if (eventType === 'error') {
          let errText = dataStr;
          try {
            const parsed = JSON.parse(dataStr);
            errText = parsed.text || parsed.message || parsed.error || dataStr;
          } catch {
            // Keep raw dataStr
          }
          onError(errText);
        }
      }
    }
  } catch (err: any) {
    if (err.name === 'AbortError') {
      return;
    }
    onError(err.message || 'Network error encountered.');
  }
}

// --- Stage 6: Chunking, Indexing, and Search API functions ---

export async function fetchDocumentIndex(documentId: string): Promise<DocumentIndexResponse> {
  const res = await fetch(`${API_BASE_URL}/api/documents/${documentId}/index`);
  if (!res.ok) {
    throw new Error('Failed to fetch document index status');
  }
  return res.json();
}

export async function triggerDocumentIndex(documentId: string, reindex: boolean = false): Promise<any> {
  const res = await fetch(`${API_BASE_URL}/api/documents/${documentId}/index/retry?reindex=${reindex}`, {
    method: 'POST',
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to trigger indexing');
  }
  return res.json();
}

export async function fetchDocumentChunks(documentId: string): Promise<DocumentChunksResponse> {
  const res = await fetch(`${API_BASE_URL}/api/documents/${documentId}/chunks`);
  if (!res.ok) {
    throw new Error('Failed to fetch document chunks');
  }
  return res.json();
}

export async function fetchChunkDetail(chunkId: string): Promise<ChunkDetailResponse> {
  const res = await fetch(`${API_BASE_URL}/api/chunks/${chunkId}`);
  if (!res.ok) {
    throw new Error('Failed to fetch chunk details');
  }
  return res.json();
}

export async function updateDocumentModeOverride(
  documentId: string,
  modeOverride: 'direct' | 'rag' | null
): Promise<DocumentItem> {
  const res = await fetch(`${API_BASE_URL}/api/documents/${documentId}/mode-override`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode_override: modeOverride }),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to update document mode override');
  }
  return res.json();
}

export async function searchDebug(payload: {
  query: string;
  mode: string;
  limit?: number;
  document_ids?: string[];
  conversation_id?: string;
}): Promise<SearchDebugResponse> {
  const res = await fetch(`${API_BASE_URL}/api/search/debug`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Search query failed');
  }
  return res.json();
}

