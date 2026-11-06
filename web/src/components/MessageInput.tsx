import React, { useState, useRef, useEffect } from 'react';
import { Send, Square, Paperclip } from 'lucide-react';
import { DocumentItem } from '../types';
import { UploadChips } from './UploadChips';

interface MessageInputProps {
  onSend: (message: string) => void;
  onStop: () => void;
  onFilesSelected: (files: File[]) => void;
  onDeleteDocument: (docId: string) => void;
  documents: DocumentItem[];
  selectedDocumentIds?: string[];
  onToggleSelectDocument?: (docId: string) => void;
  isStreaming: boolean;
  disabled?: boolean;
}

export const MessageInput: React.FC<MessageInputProps> = ({
  onSend,
  onStop,
  onFilesSelected,
  onDeleteDocument,
  documents,
  selectedDocumentIds = [],
  onToggleSelectDocument,
  isStreaming,
  disabled = false,
}) => {
  const [text, setText] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Auto-resize textarea height based on content
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`;
    }
  }, [text]);

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const trimmed = text.trim();
    const hasSelectedDocs = selectedDocumentIds.length > 0;

    if ((!trimmed && !hasSelectedDocs) || isStreaming || disabled) return;

    onSend(trimmed);
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

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const selected = Array.from(e.target.files);
      onFilesSelected(selected);
      // Reset input value so re-selecting the same file triggers change
      e.target.value = '';
    }
  };

  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const items = e.clipboardData?.items;
    if (!items) return;

    const files: File[] = [];
    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      if (item.kind === 'file') {
        const file = item.getAsFile();
        if (file) {
          files.push(file);
        }
      }
    }

    if (files.length > 0) {
      e.preventDefault();
      onFilesSelected(files);
    }
  };

  const canSend = text.trim().length > 0 || selectedDocumentIds.length > 0;

  return (
    <div className="w-full max-w-4xl mx-auto p-4">
      {/* Uploaded Documents Chips Bar */}
      <UploadChips
        documents={documents}
        selectedDocumentIds={selectedDocumentIds}
        onToggleSelectDocument={onToggleSelectDocument}
        onDeleteDocument={onDeleteDocument}
      />

      <div className="relative flex items-end bg-white border border-slate-300 rounded-2xl shadow-sm focus-within:border-indigo-500 focus-within:ring-1 focus-within:ring-indigo-500 p-2">
        {/* Hidden File Input */}
        <input
          type="file"
          ref={fileInputRef}
          onChange={handleFileChange}
          multiple
          accept=".pdf,.png,.jpg,.jpeg,.webp,.gif,.txt,.md,.csv"
          className="hidden"
        />

        {/* Paperclip Button */}
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled}
          title="Attach documents or images (PDF, PNG, JPG, TXT, CSV)"
          className="p-2 text-slate-500 hover:text-indigo-600 hover:bg-slate-100 rounded-xl transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Paperclip className="w-5 h-5" />
        </button>

        {/* Chat Textarea */}
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder={
            isStreaming
              ? 'Gemini is generating...'
              : selectedDocumentIds.length > 0
              ? 'Ask a question about the attached files, or hit Send to describe them...'
              : 'Ask a question or paste images... (Shift+Enter for newline)'
          }
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
            disabled={!canSend || disabled}
            title="Send message"
            className="p-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-200 disabled:text-slate-400 text-white rounded-xl transition-colors shadow-sm ml-2 flex items-center justify-center"
          >
            <Send className="w-4 h-4" />
          </button>
        )}
      </div>

      <div className="flex items-center justify-between text-[11px] text-slate-400 mt-2 px-1">
        <span>Drop files, paste images, or click checkboxes to include/exclude from context</span>
        <span>Grounded Direct Mode</span>
      </div>
    </div>
  );
};
