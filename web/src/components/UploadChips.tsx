import React from 'react';
import { DocumentItem } from '../types';
import { FileText, Image as ImageIcon, Loader2, CheckCircle2, AlertCircle, X } from 'lucide-react';
import { getDocumentFileUrl } from '../services/api';

interface UploadChipsProps {
  documents: DocumentItem[];
  onDeleteDocument: (docId: string) => void;
}

export function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

export const UploadChips: React.FC<UploadChipsProps> = ({ documents, onDeleteDocument }) => {
  if (documents.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2 px-2 pb-2">
      {documents.map((doc) => {
        const isImage = doc.mime_type.startsWith('image/');
        const isPdf = doc.mime_type === 'application/pdf';

        return (
          <div
            key={doc.id}
            className={`group flex items-center space-x-2 px-3 py-1.5 rounded-xl border text-xs shadow-2xs transition-all ${
              doc.status === 'failed'
                ? 'bg-rose-50/80 border-rose-200 text-rose-800'
                : doc.status === 'ready'
                ? 'bg-slate-50 border-slate-200 text-slate-700'
                : 'bg-indigo-50/70 border-indigo-200 text-indigo-900'
            }`}
          >
            {/* Thumbnail or Icon */}
            {isImage && doc.status === 'ready' ? (
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
            <div className="flex flex-col min-w-0 max-w-[130px]">
              <span className="truncate font-medium" title={doc.filename}>
                {doc.filename}
              </span>
              <span className="text-[10px] text-slate-400">
                {doc.size_bytes > 0 ? formatBytes(doc.size_bytes) : ''}
              </span>
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
              onClick={() => onDeleteDocument(doc.id)}
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
