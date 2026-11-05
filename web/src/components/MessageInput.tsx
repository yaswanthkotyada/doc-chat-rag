import React, { useState, useRef, useEffect } from 'react';
import { Send, Square, Paperclip } from 'lucide-react';

interface MessageInputProps {
  onSend: (message: string) => void;
  onStop: () => void;
  isStreaming: boolean;
  disabled?: boolean;
}

export const MessageInput: React.FC<MessageInputProps> = ({
  onSend,
  onStop,
  isStreaming,
  disabled = false,
}) => {
  const [text, setText] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea height based on content
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`;
    }
  }, [text]);

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!text.trim() || isStreaming || disabled) return;
    onSend(text.trim());
    setText('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="w-full max-w-4xl mx-auto p-4">
      <div className="relative flex items-end bg-white border border-slate-300 rounded-2xl shadow-sm focus-within:border-indigo-500 focus-within:ring-1 focus-within:ring-indigo-500 p-2">
        {/* Stage 3 File Upload Placeholder (Disabled) */}
        <button
          type="button"
          disabled
          title="Document attachment coming in Stage 3"
          className="p-2 text-slate-300 hover:text-slate-400 cursor-not-allowed rounded-lg"
        >
          <Paperclip className="w-5 h-5" />
        </button>

        {/* Chat Textarea */}
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={isStreaming ? 'Gemini is generating...' : 'Ask a question... (Shift+Enter for new line)'}
          disabled={isStreaming || disabled}
          rows={1}
          className="flex-1 max-h-44 resize-none bg-transparent px-3 py-2 text-sm text-slate-800 placeholder-slate-400 focus:outline-none disabled:bg-transparent"
        />

        {/* Action Button: Stop if streaming, Send if idle */}
        {isStreaming ? (
          <button
            type="button"
            onClick={onStop}
            title="Stop generation"
            className="p-2 bg-rose-600 hover:bg-rose-700 text-white rounded-xl transition-colors shadow-sm ml-2 flex items-center justify-center"
          >
            <Square className="w-4 h-4 fill-white" />
          </button>
        ) : (
          <button
            type="button"
            onClick={() => handleSubmit()}
            disabled={!text.trim() || disabled}
            title="Send message"
            className="p-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-200 disabled:text-slate-400 text-white rounded-xl transition-colors shadow-sm ml-2 flex items-center justify-center"
          >
            <Send className="w-4 h-4" />
          </button>
        )}
      </div>

      <div className="text-center text-[11px] text-slate-400 mt-2">
        Powered by Google Gemini 2.5 Flash • Press Enter to send
      </div>
    </div>
  );
};

