import React from 'react';
import { DocumentItem } from '../types';
import { FileText, Image as ImageIcon, Loader2, CheckCircle2, AlertCircle, X, CheckSquare, Square } from 'lucide-react';
import { getDocumentFileUrl } from '../services/api';

interface UploadChipsProps {
  documents: DocumentItem[];
  selectedDocumentIds?: string[];
  onToggleSelectDocument?: (docId: string) => void;
  onDeleteDocument: (docId: string) => void;
}

export function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

export const UploadChips: React.FC<UploadChipsProps> = ({
  documents,
  selectedDocumentIds = [],
  onToggleSelectDocument,
  onDeleteDocument,
}) => {
  if (documents.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2 px-2 pb-2">
      <span className="text-[11px] font-medium text-slate-400 mr-1">Context:</span>
      {documents.map((doc) => {
        const isImage = doc.mime_type.startsWith('image/');
        const isPdf = doc.mime_type === 'application/pdf';
        const isSelected = selectedDocumentIds.includes(doc.id);
        const isReady = doc.status === 'ready';

        return (
          <div
            key={doc.id}
            onClick={() => {
              if (isReady && onToggleSelectDocument) {
                onToggleSelectDocument(doc.id);
              }
            }}
            className={`group flex items-center space-x-2 px-2.5 py-1.5 rounded-xl border text-xs shadow-2xs transition-all select-none ${
              doc.status === 'failed'
                ? 'bg-rose-50/80 border-rose-200 text-rose-800'
                : !isSelected && isReady
                ? 'bg-slate-50/60 border-slate-200 text-slate-400 opacity-60 hover:opacity-100 cursor-pointer'
                : isSelected && isReady
                ? 'bg-indigo-50 border-indigo-300 text-indigo-950 font-medium ring-1 ring-indigo-200 cursor-pointer'
                : 'bg-indigo-50/70 border-indigo-200 text-indigo-900'
            }`}
            title={
              isReady
                ? isSelected
                  ? 'Attached to next message. Click to exclude.'
                  : 'Excluded from next message. Click to attach.'
                : doc.error || 'Uploading...'
            }
          >
            {/* Selection Checkbox (for ready documents) */}
            {isReady && onToggleSelectDocument && (
              <button
                type="button"
                className="text-indigo-600 focus:outline-none -mr-0.5"
                onClick={(e) => {
                  e.stopPropagation();
                  onToggleSelectDocument(doc.id);
                }}
              >
                {isSelected ? (
                  <CheckSquare className="w-3.5 h-3.5 text-indigo-600 fill-indigo-50" />
                ) : (
                  <Square className="w-3.5 h-3.5 text-slate-400" />
                )}
              </button>
            )}

            {/* Thumbnail or Icon */}
            {isImage && isReady ? (
              <img
                src={getDocumentFileUrl(doc.id)}
                alt={doc.filename}
                className="w-5 h-5 rounded object-cover flex-shrink-0"
              />
            ) : isPdf ? (
              <FileText className="w-4 h-4 text-rose-500 flex-shrink-0" />
            ) : isImage ? (
              <ImageIcon className="w-4 h-4 text-indigo-500 flex-shrink-0" />
            ) : (
              <FileText className="w-4 h-4 text-slate-500 flex-shrink-0" />
            )}

            {/* Filename and Size */}
            <div className="flex flex-col min-w-0 max-w-[125px]">
              <span className="truncate font-medium" title={doc.filename}>
                {doc.filename}
              </span>
              <div className="flex items-center space-x-1 text-[10px] text-slate-400">
                <span>{doc.size_bytes > 0 ? formatBytes(doc.size_bytes) : ''}</span>
                {doc.mode === 'direct' && (
                  <span className="bg-emerald-100 text-emerald-700 px-1 py-0.2 rounded font-semibold text-[9px]">
                    Direct
                  </span>
                )}
                {doc.mode === 'rag' && (
                  <span className="bg-amber-100 text-amber-700 px-1 py-0.2 rounded font-semibold text-[9px]">
                    RAG
                  </span>
                )}
              </div>
            </div>

            {/* Status Indicator */}
            {doc.status === 'uploading' && (
              <div className="flex items-center space-x-1 text-indigo-600 font-medium text-[10px]">
                <Loader2 className="w-3 h-3 animate-spin" />
                <span>{doc.uploadProgress !== undefined ? `${doc.uploadProgress}%` : 'uploading'}</span>
              </div>
            )}

            {doc.status === 'processing' && (
              <div className="flex items-center space-x-1 text-amber-600 font-medium text-[10px]">
                <Loader2 className="w-3 h-3 animate-spin" />
                <span>processing</span>
              </div>
            )}

            {doc.status === 'ready' && (
              <div className="flex items-center space-x-1 text-emerald-600">
                <CheckCircle2 className="w-3.5 h-3.5" />
                {doc.page_count ? (
                  <span className="text-[10px] text-slate-500">{doc.page_count}p</span>
                ) : doc.width && doc.height ? (
                  <span className="text-[10px] text-slate-500">{doc.width}x{doc.height}</span>
                ) : null}
              </div>
            )}

            {doc.status === 'failed' && (
              <div
                className="flex items-center space-x-1 text-rose-600 cursor-help"
                title={doc.error || 'Upload or validation failed'}
              >
                <AlertCircle className="w-3.5 h-3.5" />
                <span className="text-[10px] truncate max-w-[70px]">{doc.error || 'failed'}</span>
              </div>
            )}

            {/* Remove / Delete Button */}
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onDeleteDocument(doc.id);
              }}
              className="text-slate-400 hover:text-slate-600 p-0.5 rounded transition-colors ml-1"
              title="Remove document"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        );
      })}
    </div>
  );
};

