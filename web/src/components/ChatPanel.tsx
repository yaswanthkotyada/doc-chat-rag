import React, { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Conversation, DocumentItem, Message } from '../types';
import { MessageItem } from './MessageItem';
import { MessageInput } from './MessageInput';
import { DocumentsDrawer } from './DocumentsDrawer';
import { ParsedViewModal } from './ParsedViewModal';
import { ChunksViewModal } from './ChunksViewModal';
import { SearchDebugModal } from './SearchDebugModal';
import { retryDocumentParse, triggerDocumentIndex } from '../services/api';
import { Bot, AlertCircle, RefreshCw, MessageSquare, Files, UploadCloud, Sparkles } from 'lucide-react';

interface ChatPanelProps {
  conversation: Conversation | null;
  messages: Message[];
  streamingText: string;
  isStreaming: boolean;
  errorMessage: string | null;
  documents: DocumentItem[];
  selectedDocumentIds: string[];
  isDrawerOpen: boolean;
  onSend: (message: string) => void;
  onStop: () => void;
  onRetry: () => void;
  onFilesSelected: (files: File[]) => void;
  onToggleSelectDocument: (docId: string) => void;
  onDeleteDocument: (docId: string) => void;
  onToggleDrawer: () => void;
}

export const ChatPanel: React.FC<ChatPanelProps> = ({
  conversation,
  messages,
  streamingText,
  isStreaming,
  errorMessage,
  documents,
  selectedDocumentIds,
  isDrawerOpen,
  onSend,
  onStop,
  onRetry,
  onFilesSelected,
  onToggleSelectDocument,
  onDeleteDocument,
  onToggleDrawer,
}) => {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [userHasScrolledUp, setUserHasScrolledUp] = useState(false);
  const [isDraggingOver, setIsDraggingOver] = useState(false);
  const [inspectDoc, setInspectDoc] = useState<DocumentItem | null>(null);
  const [chunksDoc, setChunksDoc] = useState<DocumentItem | null>(null);
  const [isSearchDebugOpen, setIsSearchDebugOpen] = useState(false);
  const dragCounterRef = useRef(0);

  const handleRetryParse = async (docId: string) => {
    try {
      await retryDocumentParse(docId);
    } catch (err: any) {
      console.error('Failed to retry parse:', err);
    }
  };

  const handleRetryIndex = async (docId: string) => {
    try {
      await triggerDocumentIndex(docId, true);
    } catch (err: any) {
      console.error('Failed to trigger index:', err);
    }
  };

  // Detect whether the user has scrolled up away from bottom
  const handleScroll = () => {
    if (!scrollContainerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollContainerRef.current;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 60;
    setUserHasScrolledUp(!isAtBottom);
  };

  // Auto-scroll to bottom on new messages or stream tokens unless user scrolled up
  useEffect(() => {
    if (!userHasScrolledUp && messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, streamingText, userHasScrolledUp]);

  // Drag and drop handlers
  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current += 1;
    if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
      setIsDraggingOver(true);
    }
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current -= 1;
    if (dragCounterRef.current === 0) {
      setIsDraggingOver(false);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDraggingOver(false);
    dragCounterRef.current = 0;

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      onFilesSelected(Array.from(e.dataTransfer.files));
    }
  };

  return (
    <main
      className="flex-1 flex flex-col h-full bg-slate-50 relative overflow-hidden"
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {/* Drag & Drop Visual Overlay */}
      {isDraggingOver && (
        <div className="absolute inset-0 bg-indigo-600/10 backdrop-blur-xs border-2 border-dashed border-indigo-500 z-50 flex flex-col items-center justify-center pointer-events-none">
          <div className="bg-white px-6 py-5 rounded-2xl shadow-xl flex items-center space-x-3 text-indigo-700 animate-in fade-in zoom-in-95">
            <UploadCloud className="w-8 h-8 text-indigo-600 animate-bounce" />
            <div>
              <p className="font-semibold text-sm">Drop files to attach to conversation</p>
              <p className="text-xs text-slate-500">PDF, images, TXT, Markdown, CSV</p>
            </div>
          </div>
        </div>
      )}

      {/* Top Header */}
      <header className="h-14 border-b border-slate-200 bg-white px-6 flex items-center justify-between shadow-xs z-10 flex-shrink-0">
        <div className="flex items-center space-x-3 min-w-0">
          <MessageSquare className="w-5 h-5 text-indigo-600 flex-shrink-0" />
          <h2 className="font-semibold text-slate-800 text-sm truncate max-w-md">
            {conversation?.title || (conversation ? 'Untitled Conversation' : 'Select or Start a Chat')}
          </h2>
        </div>

        {/* Header Action Buttons */}
        <div className="flex items-center space-x-2">
          {/* Search Debug Button */}
          <button
            onClick={() => setIsSearchDebugOpen(true)}
            className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg border border-purple-200 bg-purple-50 hover:bg-purple-100 text-purple-700 text-xs font-semibold shadow-2xs transition-colors cursor-pointer"
            title="Open Search Debug Studio (Vector / Keyword / Hybrid Retrieval)"
          >
            <Sparkles className="w-4 h-4 text-purple-600" />
            <span>Search Debug</span>
          </button>

          {/* Documents Drawer Toggle Button */}
          <button
            onClick={onToggleDrawer}
            className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors cursor-pointer ${
              isDrawerOpen
                ? 'bg-indigo-50 border-indigo-300 text-indigo-700 shadow-xs'
                : 'border-slate-200 bg-white hover:bg-slate-50 text-slate-700'
            }`}
            title="View attached conversation documents"
          >
            <Files className="w-4 h-4 text-indigo-600" />
            <span>Documents</span>
            {documents.length > 0 && (
              <span className="ml-1 px-1.5 py-0.2 bg-indigo-100 text-indigo-700 text-[11px] rounded-full font-semibold">
                {documents.length}
              </span>
            )}
          </button>
        </div>
      </header>

      {/* Main Content Area + Side Drawer */}
      <div className="flex-1 flex overflow-hidden">
        {/* Messages and Input Box Area */}
        <div className="flex-1 flex flex-col h-full overflow-hidden">
          {/* Message List Area */}
          <div
            ref={scrollContainerRef}
            onScroll={handleScroll}
            className="flex-1 overflow-y-auto px-6 py-6"
          >
            <div className="max-w-4xl mx-auto space-y-4">
              {/* Empty State */}
              {messages.length === 0 && !isStreaming && !errorMessage && (
                <div className="flex flex-col items-center justify-center py-24 text-center">
                  <div className="w-14 h-14 bg-indigo-100 text-indigo-600 rounded-2xl flex items-center justify-center mb-4 shadow-sm">
                    <Bot className="w-8 h-8" />
                  </div>
                  <h3 className="text-lg font-semibold text-slate-800 mb-1">
                    How can I help you today?
                  </h3>
                  <p className="text-sm text-slate-500 max-w-md">
                    Ask any question, drag-drop documents or images, or paste screenshots directly into chat.
                  </p>
                </div>
              )}

              {/* Stored Messages */}
              {messages.map((m) => (
                <MessageItem key={m.id} message={m} />
              ))}

              {/* Active Streaming Assistant Response Bubble */}
              {isStreaming && (
                <div className="flex w-full justify-start py-2">
                  <div className="flex max-w-[82%] items-start space-x-3">
                    <div className="flex-shrink-0 w-8 h-8 rounded-full bg-slate-200 text-slate-700 flex items-center justify-center">
                      <Bot className="w-4 h-4 text-indigo-600" />
                    </div>
                    <div className="rounded-2xl rounded-tl-none px-4 py-3 text-sm bg-white border border-slate-200 text-slate-800 shadow-sm">
                      {streamingText ? (
                        <div className="prose-chat text-slate-800">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {streamingText
                              .replace(/\[\[(?:cite:[^\]]*)?$/i, '')
                              .replace(
                                /\[\[cite:\s*([^\|\]]+?)(?:\s*\|\s*p\.?\s*(\d+))?\s*\]\]/gi,
                                (_, f, p) => `[📄 ${f}${p ? ` · p.${p}` : ''}]`
                              )}
                          </ReactMarkdown>
                        </div>
                      ) : (
                        <div className="flex items-center space-x-2 text-slate-400 py-1">
                          <div className="w-2 h-2 rounded-full bg-indigo-600 animate-pulse" />
                          <div className="w-2 h-2 rounded-full bg-indigo-600 animate-pulse delay-75" />
                          <div className="w-2 h-2 rounded-full bg-indigo-600 animate-pulse delay-150" />
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {/* Error Banner */}
              {errorMessage && (
                <div className="my-4 p-4 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 flex items-start justify-between shadow-xs">
                  <div className="flex items-start space-x-3">
                    <AlertCircle className="w-5 h-5 text-rose-600 flex-shrink-0 mt-0.5" />
                    <div className="text-sm">
                      <span className="font-semibold block mb-0.5">Error</span>
                      <span>{errorMessage}</span>
                    </div>
                  </div>
                  <button
                    onClick={onRetry}
                    className="flex items-center space-x-1.5 px-3 py-1.5 bg-rose-100 hover:bg-rose-200 text-rose-800 rounded-lg text-xs font-medium transition-colors"
                  >
                    <RefreshCw className="w-3.5 h-3.5" />
                    <span>Retry</span>
                  </button>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>
          </div>

          {/* Input Box */}
          <footer className="border-t border-slate-200 bg-white">
            <MessageInput
              onSend={onSend}
              onStop={onStop}
              onFilesSelected={onFilesSelected}
              onDeleteDocument={onDeleteDocument}
              documents={documents}
              selectedDocumentIds={selectedDocumentIds}
              onToggleSelectDocument={onToggleSelectDocument}
              isStreaming={isStreaming}
              disabled={!conversation}
            />
          </footer>
        </div>

        {/* Documents Side Drawer */}
        <DocumentsDrawer
          documents={documents}
          isOpen={isDrawerOpen}
          onClose={onToggleDrawer}
          onDeleteDocument={onDeleteDocument}
          onViewParsed={setInspectDoc}
          onRetryParse={handleRetryParse}
          onViewChunks={setChunksDoc}
          onRetryIndex={handleRetryIndex}
        />

        {/* Parsed Document Modal */}
        <ParsedViewModal
          document={inspectDoc}
          isOpen={Boolean(inspectDoc)}
          onClose={() => setInspectDoc(null)}
        />

        {/* Chunks Inspector Modal (Stage 6) */}
        <ChunksViewModal
          document={chunksDoc}
          isOpen={Boolean(chunksDoc)}
          onClose={() => setChunksDoc(null)}
        />

        {/* Search Debug Studio (Stage 6) */}
        <SearchDebugModal
          isOpen={isSearchDebugOpen}
          onClose={() => setIsSearchDebugOpen(false)}
          conversationId={conversation?.id}
          documents={documents}
        />
      </div>
    </main>
  );
};

