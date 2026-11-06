import React, { useState } from 'react';
import { DocumentItem } from '../types';
import { getDocumentFileUrl } from '../services/api';
import { formatBytes } from './UploadChips';
import {
  FileText,
  Image as ImageIcon,
  ExternalLink,
  Trash2,
  CheckCircle2,
  AlertCircle,
  Loader2,
  X,
  FileCode,
} from 'lucide-react';

interface DocumentsDrawerProps {
  documents: DocumentItem[];
  isOpen: boolean;
  onClose: () => void;
  onDeleteDocument: (docId: string) => void;
}

export const DocumentsDrawer: React.FC<DocumentsDrawerProps> = ({
  documents,
  isOpen,
  onClose,
  onDeleteDocument,
}) => {
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleDeleteClick = (docId: string) => {
    if (confirmDeleteId === docId) {
      onDeleteDocument(docId);
      setConfirmDeleteId(null);
    } else {
      setConfirmDeleteId(docId);
    }
  };

  return (
    <aside className="w-80 border-l border-slate-200 bg-white flex flex-col h-full shadow-lg z-20 transition-all">
      {/* Drawer Header */}
      <div className="h-14 px-4 border-b border-slate-200 flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <FileText className="w-5 h-5 text-indigo-600" />
          <h3 className="font-semibold text-slate-800 text-sm">Conversation Documents</h3>
          <span className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full font-medium">
            {documents.length}
          </span>
        </div>
        <button
          onClick={onClose}
          className="text-slate-400 hover:text-slate-600 p-1 rounded-lg"
          title="Close panel"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Documents List */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {documents.length === 0 ? (
          <div className="text-center py-16 text-slate-400 text-sm">
            <FileText className="w-8 h-8 mx-auto mb-2 text-slate-300" />
            <p>No documents attached yet.</p>
            <p className="text-xs text-slate-400 mt-1">Upload PDFs, images, or text files using the paperclip or drag-and-drop.</p>
          </div>
        ) : (
          documents.map((doc) => {
            const isImage = doc.mime_type.startsWith('image/');
            const isPdf = doc.mime_type === 'application/pdf';
            const fileUrl = getDocumentFileUrl(doc.id);

            return (
              <div
                key={doc.id}
                className="p-3 border border-slate-200 rounded-xl hover:border-slate-300 transition-all bg-slate-50/50"
              >
                <div className="flex items-start justify-between">
                  {/* File Thumbnail or Icon */}
                  <div className="flex items-start space-x-2.5 min-w-0 flex-1">
                    {isImage && doc.status === 'ready' ? (
                      <a href={fileUrl} target="_blank" rel="noopener noreferrer" className="flex-shrink-0">
                        <img
                          src={fileUrl}
                          alt={doc.filename}
                          className="w-10 h-10 rounded-lg object-cover border border-slate-200 hover:opacity-90 transition-opacity"
                        />
                      </a>
                    ) : isPdf ? (
                      <div className="w-10 h-10 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center flex-shrink-0">
                        <FileText className="w-5 h-5" />
                      </div>
                    ) : isImage ? (
                      <div className="w-10 h-10 rounded-lg bg-indigo-100 text-indigo-600 flex items-center justify-center flex-shrink-0">
                        <ImageIcon className="w-5 h-5" />
                      </div>
                    ) : (
                      <div className="w-10 h-10 rounded-lg bg-slate-200 text-slate-600 flex items-center justify-center flex-shrink-0">
                        <FileCode className="w-5 h-5" />
                      </div>
                    )}

                    {/* Metadata */}
                    <div className="min-w-0 flex-1">
                      <div className="text-xs font-semibold text-slate-800 truncate" title={doc.filename}>
                        {doc.filename}
                      </div>

                      <div className="text-[11px] text-slate-500 mt-0.5 flex flex-wrap gap-x-2">
                        <span>{formatBytes(doc.size_bytes)}</span>
                        {doc.page_count && <span>• {doc.page_count} pages</span>}
                        {doc.width && doc.height && <span>• {doc.width}×{doc.height}</span>}
                        {doc.meta?.lines && <span>• {doc.meta.lines} lines</span>}
                      </div>

                      {/* Status & Mode */}
                      <div className="mt-1 flex items-center space-x-1.5 text-[11px]">
                        {doc.status === 'ready' && (
                          <span className="flex items-center text-emerald-600 space-x-1">
                            <CheckCircle2 className="w-3 h-3" />
                            <span>Ready</span>
                          </span>
                        )}
                        {doc.mode === 'direct' && (
                          <span className="bg-emerald-100 text-emerald-700 px-1.5 py-0.2 rounded font-semibold text-[10px]">
                            Direct
                          </span>
                        )}
                        {doc.mode === 'rag' && (
                          <span className="bg-amber-100 text-amber-700 px-1.5 py-0.2 rounded font-semibold text-[10px]" title="File exceeds direct mode limits; reserved for RAG stage">
                            RAG (Large)
                          </span>
                        )}
                        {doc.status === 'processing' && (
                          <span className="flex items-center text-amber-600 space-x-1">
                            <Loader2 className="w-3 h-3 animate-spin" />
                            <span>Processing...</span>
                          </span>
                        )}
                        {doc.status === 'uploading' && (
                          <span className="flex items-center text-indigo-600 space-x-1">
                            <Loader2 className="w-3 h-3 animate-spin" />
                            <span>Uploading ({doc.uploadProgress || 0}%)...</span>
                          </span>
                        )}
                        {doc.status === 'failed' && (
                          <span className="flex items-center text-rose-600 space-x-1" title={doc.error || 'Failed'}>
                            <AlertCircle className="w-3 h-3 flex-shrink-0" />
                            <span className="truncate max-w-[140px]">{doc.error || 'Failed'}</span>
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center space-x-1 ml-2">
                    {doc.status === 'ready' && (
                      <a
                        href={fileUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="p-1.5 text-slate-400 hover:text-indigo-600 rounded transition-colors"
                        title="Open file in new tab"
                      >
                        <ExternalLink className="w-3.5 h-3.5" />
                      </a>
                    )}
                    <button
                      onClick={() => handleDeleteClick(doc.id)}
                      className={`p-1.5 rounded transition-colors text-xs flex items-center space-x-1 ${
                        confirmDeleteId === doc.id
                          ? 'bg-rose-600 text-white hover:bg-rose-700 px-2'
                          : 'text-slate-400 hover:text-rose-600'
                      }`}
                      title={confirmDeleteId === doc.id ? 'Click again to confirm delete' : 'Delete document'}
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                      {confirmDeleteId === doc.id && <span>Delete?</span>}
                    </button>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </aside>
  );
};

