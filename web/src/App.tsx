import React, { useEffect, useState, useRef, useCallback } from 'react';
import { Conversation, DocumentItem, HealthStatus, Message } from './types';
import { Sidebar } from './components/Sidebar';
import { ChatPanel } from './components/ChatPanel';
import {
  fetchHealth,
  fetchConversations,
  fetchConversation,
  createConversation,
  deleteConversation,
  streamChatMessage,
  fetchDocuments,
  fetchDocument,
  uploadDocuments,
  deleteDocument,
} from './services/api';

const MAX_UPLOAD_MB = 50;
const MAX_FILES_PER_REQUEST = 5;
const MAX_FILES_PER_CONVERSATION = 10;
const OFFICE_EXTENSIONS = ['.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt'];

export const App: React.FC = () => {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [activeConversation, setActiveConversation] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([]);
  const [isDrawerOpen, setIsDrawerOpen] = useState<boolean>(false);
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
      const [fullConv, docs] = await Promise.all([
        fetchConversation(id),
        fetchDocuments(id),
      ]);
      setActiveConversation(fullConv);
      setMessages(fullConv.messages || []);
      setDocuments(docs);
      // Auto-select ready direct mode documents for context
      setSelectedDocumentIds(
        docs.filter((d) => d.status === 'ready' && d.mode !== 'rag').map((d) => d.id)
      );
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to load conversation history.');
    }
  };

  // Poll non-terminal documents every ~1.5s until terminal status (ready or failed)
  useEffect(() => {
    const nonTerminalDocs = documents.filter(
      (d) =>
        (d.status === 'processing' ||
          d.status === 'uploading' ||
          d.parse_status === 'parsing' ||
          d.parse_status === 'pending') &&
        !d.id.startsWith('temp-')
    );
    if (nonTerminalDocs.length === 0) return;

    let isMounted = true;
    const timer = setTimeout(async () => {
      try {
        const updates = await Promise.all(
          nonTerminalDocs.map(async (doc) => {
            try {
              return await fetchDocument(doc.id);
            } catch {
              return doc;
            }
          })
        );

        if (!isMounted) return;

        setDocuments((prev) =>
          prev.map((d) => {
            const found = updates.find((u) => u.id === d.id);
            return found ? found : d;
          })
        );
      } catch {
        // Ignore polling errors
      }
    }, 1500);

    return () => {
      isMounted = false;
      clearTimeout(timer);
    };
  }, [documents, activeId]);

  // Create a new chat
  const handleNewChat = async () => {
    if (isStreaming) {
      handleStop();
    }
    setErrorMessage(null);
    setStreamingText('');
    setDocuments([]);
    setSelectedDocumentIds([]);

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
        setDocuments([]);
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

  // Delete document
  const handleDeleteDocument = async (docId: string) => {
    try {
      await deleteDocument(docId);
      setDocuments((prev) => prev.filter((d) => d.id !== docId));
      setSelectedDocumentIds((prev) => prev.filter((id) => id !== docId));
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to delete document.');
    }
  };

  // Toggle document selection for message context
  const handleToggleSelectDocument = (docId: string) => {
    setSelectedDocumentIds((prev) =>
      prev.includes(docId) ? prev.filter((id) => id !== docId) : [...prev, docId]
    );
  };

  // Handle file selection from paperclip, drag-and-drop, or clipboard paste
  const handleFilesSelected = async (files: File[]) => {
    if (!files || files.length === 0) return;

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

    // Client-side pre-checks
    if (files.length > MAX_FILES_PER_REQUEST) {
      setErrorMessage(`Cannot upload more than ${MAX_FILES_PER_REQUEST} files at a time.`);
      return;
    }

    if (documents.length + files.length > MAX_FILES_PER_CONVERSATION) {
      setErrorMessage(
        `Conversation cannot exceed ${MAX_FILES_PER_CONVERSATION} files (currently ${documents.length}).`
      );
      return;
    }

    for (const f of files) {
      const ext = '.' + f.name.split('.').pop()?.toLowerCase();
      if (OFFICE_EXTENSIONS.includes(ext)) {
        setErrorMessage('Office files will be supported in a later stage');
        return;
      }
      if (f.size > MAX_UPLOAD_MB * 1024 * 1024) {
        setErrorMessage(`"${f.name}" exceeds the maximum size limit of ${MAX_UPLOAD_MB}MB.`);
        return;
      }
    }

    setErrorMessage(null);

    // Create optimistic temporary items
    const tempIds = files.map((_, i) => `temp-${Date.now()}-${i}`);
    const optimisticDocs: DocumentItem[] = files.map((f, i) => ({
      id: tempIds[i],
      conversation_id: convId!,
      filename: f.name,
      mime_type: f.type || 'application/octet-stream',
      size_bytes: f.size,
      status: 'uploading',
      uploadProgress: 0,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }));

    setDocuments((prev) => [...prev, ...optimisticDocs]);

    try {
      const uploaded = await uploadDocuments(convId, files, (percent) => {
        setDocuments((prev) =>
          prev.map((d) => (tempIds.includes(d.id) ? { ...d, uploadProgress: percent } : d))
        );
      });

      // Replace optimistic docs with server response
      setDocuments((prev) => {
        const withoutTemp = prev.filter((d) => !tempIds.includes(d.id));
        return [...withoutTemp, ...uploaded];
      });

      // Auto-select uploaded documents that are not failed
      const newIds = uploaded.filter((d) => d.status !== 'failed').map((d) => d.id);
      setSelectedDocumentIds((prev) => Array.from(new Set([...prev, ...newIds])));
    } catch (err: any) {
      // Mark optimistic docs as failed with error
      setDocuments((prev) =>
        prev.map((d) =>
          tempIds.includes(d.id)
            ? { ...d, status: 'failed', error: err.message || 'Upload failed' }
            : d
        )
      );
      setErrorMessage(err.message || 'File upload failed.');
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

    // Display text: default to "Describe this file." if user sent empty with files attached
    const displayText = text.trim() || (selectedDocumentIds.length > 0 ? "Describe this file." : "");

    // Resolve attached documents for this message
    const attachedDocs = documents.filter((d) => selectedDocumentIds.includes(d.id));
    const attachedSummary = attachedDocs.map((d) => ({
      id: d.id,
      filename: d.filename,
      mime_type: d.mime_type,
      size_bytes: d.size_bytes,
      page_count: d.page_count,
      mode: d.mode,
    }));

    // Optimistically append user message with attached_documents in meta
    const tempUserMsg: Message = {
      id: `temp-${Date.now()}`,
      conversation_id: convId,
      role: 'user',
      content: displayText,
      meta: attachedSummary.length > 0 ? { attached_documents: attachedSummary } : null,
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
      documentIds: selectedDocumentIds,
      signal: controller.signal,
      onToken: (chunk) => {
        accumulated += chunk;
        setStreamingText(accumulated);
      },
      onDone: async (messageId, citations, usage) => {
        setIsStreaming(false);
        abortControllerRef.current = null;
        lastFailedMessageRef.current = null;

        const metaPayload: any = {};
        if (citations && citations.length > 0) metaPayload.citations = citations;
        if (usage) metaPayload.usage = usage;

        // Append assistant message
        const assistantMsg: Message = {
          id: messageId || `done-${Date.now()}`,
          conversation_id: convId!,
          role: 'assistant',
          content: accumulated,
          meta: Object.keys(metaPayload).length > 0 ? metaPayload : null,
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
        documents={documents}
        selectedDocumentIds={selectedDocumentIds}
        isDrawerOpen={isDrawerOpen}
        streamingText={streamingText}
        isStreaming={isStreaming}
        errorMessage={errorMessage}
        onSend={handleSend}
        onStop={handleStop}
        onRetry={handleRetry}
        onFilesSelected={handleFilesSelected}
        onToggleSelectDocument={handleToggleSelectDocument}
        onDeleteDocument={handleDeleteDocument}
        onToggleDrawer={() => setIsDrawerOpen((prev) => !prev)}
      />
    </div>
  );
};

export default App;

