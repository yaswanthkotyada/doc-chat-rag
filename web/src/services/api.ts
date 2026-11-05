import { Conversation, HealthStatus, Message } from '../types';

export const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

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

export async function streamChatMessage({
  conversationId,
  message,
  onToken,
  onDone,
  onError,
  signal,
}: {
  conversationId: string;
  message: string;
  onToken: (chunk: string) => void;
  onDone: (messageId: string) => void;
  onError: (error: string) => void;
  signal?: AbortSignal;
}): Promise<void> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conversation_id: conversationId, message }),
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
        // Fallback to response status text
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

        if (eventType === 'token') {
          try {
            const parsed = JSON.parse(dataStr);
            onToken(parsed.text !== undefined ? parsed.text : dataStr);
          } catch {
            onToken(dataStr);
          }
        } else if (eventType === 'done') {
          try {
            const parsed = JSON.parse(dataStr);
            onDone(parsed.message_id || '');
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
      // Aborted intentionally by user clicking Stop
      return;
    }
    onError(err.message || 'Network error encountered.');
  }
}

