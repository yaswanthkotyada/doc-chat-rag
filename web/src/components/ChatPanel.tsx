import React, { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Conversation, Message } from '../types';
import { MessageItem } from './MessageItem';
import { MessageInput } from './MessageInput';
import { Bot, AlertCircle, RefreshCw, MessageSquare } from 'lucide-react';

interface ChatPanelProps {
  conversation: Conversation | null;
  messages: Message[];
  streamingText: string;
  isStreaming: boolean;
  errorMessage: string | null;
  onSend: (message: string) => void;
  onStop: () => void;
  onRetry: () => void;
}

export const ChatPanel: React.FC<ChatPanelProps> = ({
  conversation,
  messages,
  streamingText,
  isStreaming,
  errorMessage,
  onSend,
  onStop,
  onRetry,
}) => {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [userHasScrolledUp, setUserHasScrolledUp] = useState(false);

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

  return (
    <main className="flex-1 flex flex-col h-full bg-slate-50 relative overflow-hidden">
      {/* Top Header */}
      <header className="h-14 border-b border-slate-200 bg-white px-6 flex items-center justify-between shadow-xs">
        <div className="flex items-center space-x-3">
          <MessageSquare className="w-5 h-5 text-indigo-600" />
          <h2 className="font-semibold text-slate-800 text-sm truncate max-w-md">
            {conversation?.title || (conversation ? 'Untitled Conversation' : 'Select or Start a Chat')}
          </h2>
        </div>
      </header>

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
                Ask any question to start a streaming conversation with Gemini.
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
                        {streamingText}
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
          isStreaming={isStreaming}
          disabled={!conversation}
        />
      </footer>
    </main>
  );
};

