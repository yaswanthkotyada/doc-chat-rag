import React, { useEffect, useState, useRef, useCallback } from 'react';
import { Conversation, HealthStatus, Message } from './types';
import { Sidebar } from './components/Sidebar';
import { ChatPanel } from './components/ChatPanel';
import {
  fetchHealth,
  fetchConversations,
  fetchConversation,
  createConversation,
  deleteConversation,
  streamChatMessage,
} from './services/api';

export const App: React.FC = () => {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [activeConversation, setActiveConversation] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [streamingText, setStreamingText] = useState<string>('');
  const [isStreaming, setIsStreaming] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [healthLoading, setHealthLoading] = useState<boolean>(false);

  const abortControllerRef = useRef<AbortController | null>(null);
  const lastFailedMessageRef = useRef<string | null>(null);

  // Parse conversation ID from URL path (e.g., /c/:id or direct)
  const getUrlConversationId = (): string | null => {
    const match = window.location.pathname.match(/\/c\/([a-zA-Z0-9-]+)/);
    return match ? match[1] : null;
  };

  const updateUrl = (id: string | null) => {
    const targetPath = id ? `/c/${id}` : '/';
    if (window.location.pathname !== targetPath) {
      window.history.pushState(null, '', targetPath);
    }
  };

  // Check backend health
  const checkHealthStatus = useCallback(async () => {
    setHealthLoading(true);
    try {
      const data = await fetchHealth();
      setHealth(data);
    } catch {
      setHealth({
        api: 'error',
        db: 'error',
        pgvector: 'missing',
        gemini_key_configured: false,
      });
    } finally {
      setHealthLoading(false);
    }
  }, []);

  // Load conversation list and initial active conversation
  const loadInitialData = useCallback(async () => {
    try {
      const list = await fetchConversations();
      setConversations(list);

      const urlId = getUrlConversationId();
      if (urlId && list.some((c) => c.id === urlId)) {
        await selectConversation(urlId);
      } else if (list.length > 0) {
        await selectConversation(list[0].id);
      } else {
        // Auto-create initial new chat if none exist
        await handleNewChat();
      }
    } catch (err: any) {
      setErrorMessage('Could not connect to the API. Make sure the API service is running.');
    }
  }, []);

  useEffect(() => {
    checkHealthStatus();
    loadInitialData();

    // Listen to browser forward/backward buttons
    const handlePopState = () => {
      const id = getUrlConversationId();
      if (id) {
        selectConversation(id, false);
      }
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, [checkHealthStatus, loadInitialData]);

  // Select and load a conversation
  const selectConversation = async (id: string, syncUrl: boolean = true) => {
    if (isStreaming) {
      handleStop();
    }
    setActiveId(id);
    setErrorMessage(null);
    setStreamingText('');
    if (syncUrl) updateUrl(id);

    try {
      const fullConv = await fetchConversation(id);
      setActiveConversation(fullConv);
      setMessages(fullConv.messages || []);
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to load conversation history.');
    }
  };

  // Create a new chat
  const handleNewChat = async () => {
    if (isStreaming) {
      handleStop();
    }
    setErrorMessage(null);
    setStreamingText('');

    try {
      const newConv = await createConversation();
      setConversations((prev) => [
        {
          id: newConv.id,
          title: newConv.title,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
        ...prev,
      ]);
      setActiveId(newConv.id);
      setActiveConversation({
        id: newConv.id,
        title: newConv.title,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
      setMessages([]);
      updateUrl(newConv.id);
    } catch (err: any) {
      setErrorMessage('Failed to create new conversation.');
    }
  };

  // Delete conversation
  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await deleteConversation(id);
      const remaining = conversations.filter((c) => c.id !== id);
      setConversations(remaining);

      if (activeId === id) {
        if (remaining.length > 0) {
          await selectConversation(remaining[0].id);
        } else {
          await handleNewChat();
        }
      }
    } catch (err: any) {
      setErrorMessage('Failed to delete conversation.');
    }
  };

  // Send a message and stream reply
  const handleSend = async (text: string) => {
    let convId = activeId;
    if (!convId) {
      try {
        const newConv = await createConversation();
        convId = newConv.id;
        setActiveId(newConv.id);
        setActiveConversation(newConv as Conversation);
        setConversations((prev) => [newConv as Conversation, ...prev]);
        updateUrl(newConv.id);
      } catch {
        setErrorMessage('Failed to initiate conversation.');
        return;
      }
    }

    setErrorMessage(null);
    lastFailedMessageRef.current = text;

    // Optimistically append user message
    const tempUserMsg: Message = {
      id: `temp-${Date.now()}`,
      conversation_id: convId,
      role: 'user',
      content: text,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUserMsg]);
    setIsStreaming(true);
    setStreamingText('');

    const controller = new AbortController();
    abortControllerRef.current = controller;

    let accumulated = '';

    await streamChatMessage({
      conversationId: convId,
      message: text,
      signal: controller.signal,
      onToken: (chunk) => {
        accumulated += chunk;
        setStreamingText(accumulated);
      },
      onDone: async (messageId) => {
        setIsStreaming(false);
        abortControllerRef.current = null;
        lastFailedMessageRef.current = null;

        // Append assistant message
        const assistantMsg: Message = {
          id: messageId || `done-${Date.now()}`,
          conversation_id: convId!,
          role: 'assistant',
          content: accumulated,
          created_at: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, assistantMsg]);
        setStreamingText('');

        // Refresh conversation list to pick up auto-title and updated timestamps
        try {
          const list = await fetchConversations();
          setConversations(list);
          const current = list.find((c) => c.id === convId);
          if (current) {
            setActiveConversation((prev) => (prev ? { ...prev, title: current.title } : current));
          }
        } catch {
          // Ignore list refresh errors
        }
      },
      onError: (err) => {
        setIsStreaming(false);
        abortControllerRef.current = null;
        setErrorMessage(err);
      },
    });
  };

  // Stop button handler
  const handleStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsStreaming(false);

    if (streamingText) {
      // Append interrupted message locally
      const interruptedMsg: Message = {
        id: `interrupted-${Date.now()}`,
        conversation_id: activeId || '',
        role: 'assistant',
        content: streamingText,
        meta: { interrupted: true },
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, interruptedMsg]);
      setStreamingText('');
    }
  };

  // Retry sending last failed message
  const handleRetry = () => {
    if (lastFailedMessageRef.current) {
      handleSend(lastFailedMessageRef.current);
    }
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-white">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        onSelect={(id) => selectConversation(id)}
        onNewChat={handleNewChat}
        onDelete={handleDelete}
        health={health}
        healthLoading={healthLoading}
        onRefreshHealth={checkHealthStatus}
      />

      <ChatPanel
        conversation={activeConversation}
        messages={messages}
        streamingText={streamingText}
        isStreaming={isStreaming}
        errorMessage={errorMessage}
        onSend={handleSend}
        onStop={handleStop}
        onRetry={handleRetry}
      />
    </div>
  );
};

export default App;

