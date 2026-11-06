import React, { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Code,
  Download,
  ExternalLink,
  Eye,
  FileCode,
  FileText,
  Image as ImageIcon,
  Loader2,
  Table as TableIcon,
  X,
} from 'lucide-react';

import {
  DocumentItem,
  DocumentPageDetail,
  DocumentParseResponse,
} from '../types';
import {
  fetchDocumentPageDetail,
  fetchDocumentParse,
  getDocumentFileUrl,
  getDocumentParsedMdUrl,
} from '../services/api';

interface ParsedViewModalProps {
  document: DocumentItem | null;
  isOpen: boolean;
  onClose: () => void;
}

export const ParsedViewModal: React.FC<ParsedViewModalProps> = ({
  document,
  isOpen,
  onClose,
}) => {
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [jumpInput, setJumpInput] = useState<string>('1');
  const [pageDetail, setPageDetail] = useState<DocumentPageDetail | null>(null);
  const [parseInfo, setParseInfo] = useState<DocumentParseResponse | null>(null);
  const [loadingPage, setLoadingPage] = useState<boolean>(false);
  const [viewMode, setViewMode] = useState<'rendered' | 'raw'>('rendered');
  const [fetchError, setFetchError] = useState<string | null>(null);

  const totalPages =
    parseInfo?.total_pages ||
    parseInfo?.pages_parsed ||
    document?.page_count ||
    1;

  // Reset state when opening a new document
  useEffect(() => {
    if (isOpen && document) {
      setCurrentPage(1);
      setJumpInput('1');
      setPageDetail(null);
      setFetchError(null);

      fetchDocumentParse(document.id)
        .then((info) => setParseInfo(info))
        .catch((err) => console.error('Failed to load parse info:', err));
    }
  }, [isOpen, document?.id]);

  // Fetch page details when currentPage changes
  useEffect(() => {
    if (!isOpen || !document) return;

    let isMounted = true;
    setLoadingPage(true);
    setFetchError(null);

    fetchDocumentPageDetail(document.id, currentPage)
      .then((detail) => {
        if (isMounted) {
          setPageDetail(detail);
          setJumpInput(String(currentPage));
        }
      })
      .catch((err) => {
        if (isMounted) {
          setFetchError(err.message || `Failed to load page ${currentPage}`);
        }
      })
      .finally(() => {
        if (isMounted) {
          setLoadingPage(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [isOpen, document?.id, currentPage]);

  if (!isOpen || !document) return null;

  const handlePrev = () => {
    if (currentPage > 1) {
      setCurrentPage((prev) => prev - 1);
    }
  };

  const handleNext = () => {
    if (currentPage < totalPages) {
      setCurrentPage((prev) => prev + 1);
    }
  };

  const handleJumpSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const p = parseInt(jumpInput, 10);
    if (!isNaN(p) && p >= 1 && p <= totalPages) {
      setCurrentPage(p);
    } else {
      setJumpInput(String(currentPage));
    }
  };

  const fileUrl = getDocumentFileUrl(document.id);
  const pdfPageUrl = `${fileUrl}#page=${currentPage}&navpanes=0&toolbar=0`;
  const parsedMdUrl = getDocumentParsedMdUrl(document.id);

  const ws = parseInfo?.warnings_summary;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/70 backdrop-blur-xs p-4 sm:p-6 animate-in fade-in duration-200">
      <div className="bg-white rounded-2xl shadow-2xl border border-slate-200 w-full max-w-7xl h-[92vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="px-5 py-3.5 border-b border-slate-200 bg-slate-50/80 flex items-center justify-between flex-shrink-0">
          <div className="flex items-center space-x-3 min-w-0">
            <div className="w-9 h-9 rounded-xl bg-indigo-50 border border-indigo-100 flex items-center justify-center text-indigo-600 flex-shrink-0">
              <FileCode className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center space-x-2">
                <h3 className="text-sm font-bold text-slate-800 truncate" title={document.filename}>
                  {document.filename}
                </h3>
                <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-indigo-100 text-indigo-700">
                  Parsed View
                </span>
                {parseInfo?.parser_name && (
                  <span className="text-[11px] text-slate-500 font-mono">
                    {parseInfo.parser_name} v{parseInfo.parser_version || '1.38'}
                  </span>
                )}
              </div>
              <p className="text-[11px] text-slate-500">
                Compare original PDF page against Docling parsed Markdown side-by-side
              </p>
            </div>
          </div>

          <div className="flex items-center space-x-2 flex-shrink-0">
            <a
              href={parsedMdUrl}
              download
              className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-white border border-slate-300 text-slate-700 hover:bg-slate-50 hover:text-slate-900 transition-colors shadow-2xs no-underline"
              title="Download full parsed Markdown (.md)"
            >
              <Download className="w-3.5 h-3.5" />
              <span>Download .md</span>
            </a>
            <button
              onClick={onClose}
              className="p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-200/60 rounded-lg transition-colors"
              title="Close modal"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Quality Summary Banner */}
        {ws && (
          <div className="px-5 py-2 bg-indigo-50/60 border-b border-indigo-100/60 flex items-center justify-between text-xs text-slate-600 flex-shrink-0 flex-wrap gap-2">
            <div className="flex items-center space-x-4">
              <span>
                <strong>Total Characters:</strong> {ws.total_characters.toLocaleString()}
              </span>
              <span>
                <strong>Tables:</strong> {ws.pages_with_tables} pages
              </span>
              <span>
                <strong>Figures:</strong> {ws.pages_with_figures} pages
              </span>
              {ws.low_text_pages.length > 0 && (
                <span className="text-amber-700 font-medium">
                  <strong>Low Text:</strong> {ws.low_text_pages.length} pages (p. {ws.low_text_pages.slice(0, 5).join(', ')}{ws.low_text_pages.length > 5 ? '…' : ''})
                </span>
              )}
            </div>
            {parseInfo?.duration_seconds && (
              <span className="text-slate-400 font-mono text-[11px]">
                Parse time: {parseInfo.duration_seconds}s
              </span>
            )}
          </div>
        )}

        {/* Split Screen Body */}
        <div className="flex-1 min-h-0 grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x divide-slate-200 bg-slate-100/50">
          {/* Left Column: Original PDF Page */}
          <div className="flex flex-col min-h-0 bg-white">
            <div className="px-4 py-2 border-b border-slate-200 bg-slate-50/60 flex items-center justify-between flex-shrink-0">
              <span className="text-xs font-semibold text-slate-700 flex items-center space-x-1.5">
                <FileText className="w-3.5 h-3.5 text-rose-500" />
                <span>Original PDF (Page {currentPage} of {totalPages})</span>
              </span>
              <a
                href={fileUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[11px] font-medium text-indigo-600 hover:text-indigo-800 flex items-center space-x-1 no-underline"
              >
                <span>Open in Tab</span>
                <ExternalLink className="w-3 h-3" />
              </a>
            </div>
            <div className="flex-1 min-h-0 bg-slate-800 relative">
              <iframe
                key={`pdf-${document.id}-${currentPage}`}
                src={pdfPageUrl}
                className="w-full h-full border-0"
                title={`Original PDF Page ${currentPage}`}
              />
            </div>
          </div>

          {/* Right Column: Parsed Markdown for Current Page */}
          <div className="flex flex-col min-h-0 bg-white">
            <div className="px-4 py-2 border-b border-slate-200 bg-slate-50/60 flex items-center justify-between flex-shrink-0">
              <div className="flex items-center space-x-2">
                <span className="text-xs font-semibold text-slate-700">Parsed Content</span>

                {/* Page Attribute Badges */}
                {pageDetail?.has_table && (
                  <span className="inline-flex items-center space-x-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-100 text-emerald-800">
                    <TableIcon className="w-3 h-3" />
                    <span>Table</span>
                  </span>
                )}
                {pageDetail?.has_figure && (
                  <span className="inline-flex items-center space-x-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-purple-100 text-purple-800">
                    <ImageIcon className="w-3 h-3" />
                    <span>Figure</span>
                  </span>
                )}
                {pageDetail?.ocr_used && (
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-sky-100 text-sky-800">
                    OCR
                  </span>
                )}
                {pageDetail?.warnings?.map((w, idx) => (
                  <span
                    key={idx}
                    className="inline-flex items-center space-x-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-100 text-amber-800"
                    title={`Warning on page ${currentPage}: ${w}`}
                  >
                    <AlertTriangle className="w-3 h-3 text-amber-600" />
                    <span>{w}</span>
                  </span>
                ))}
              </div>

              {/* View Mode Toggle */}
              <div className="flex items-center p-0.5 bg-slate-200/80 rounded-lg text-xs font-medium text-slate-600">
                <button
                  onClick={() => setViewMode('rendered')}
                  className={`flex items-center space-x-1 px-2.5 py-1 rounded-md transition-all ${
                    viewMode === 'rendered'
                      ? 'bg-white text-slate-900 shadow-2xs font-semibold'
                      : 'hover:text-slate-900'
                  }`}
                >
                  <Eye className="w-3.5 h-3.5" />
                  <span>Rendered</span>
                </button>
                <button
                  onClick={() => setViewMode('raw')}
                  className={`flex items-center space-x-1 px-2.5 py-1 rounded-md transition-all ${
                    viewMode === 'raw'
                      ? 'bg-white text-slate-900 shadow-2xs font-semibold'
                      : 'hover:text-slate-900'
                  }`}
                >
                  <Code className="w-3.5 h-3.5" />
                  <span>Raw Markdown</span>
                </button>
              </div>
            </div>

            {/* Markdown Container */}
            <div className="flex-1 min-h-0 overflow-y-auto p-6">
              {loadingPage ? (
                <div className="h-full flex flex-col items-center justify-center text-slate-400 space-y-2">
                  <Loader2 className="w-6 h-6 animate-spin text-indigo-500" />
                  <span className="text-xs">Loading page {currentPage}...</span>
                </div>
              ) : fetchError ? (
                <div className="p-4 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs">
                  <p className="font-semibold">Failed to load parsed page content</p>
                  <p className="mt-1 text-rose-600">{fetchError}</p>
                </div>
              ) : !pageDetail || (!pageDetail.markdown && !pageDetail.plain_text) ? (
                <div className="h-full flex flex-col items-center justify-center text-slate-400">
                  <FileText className="w-10 h-10 stroke-1 mb-2 opacity-50" />
                  <p className="text-xs">No text detected on this page.</p>
                </div>
              ) : viewMode === 'rendered' ? (
                <div className="prose prose-slate max-w-none text-sm dark:prose-invert">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {pageDetail.markdown}
                  </ReactMarkdown>
                </div>
              ) : (
                <div className="space-y-4">
                  <div>
                    <h5 className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1">
                      Raw Markdown
                    </h5>
                    <pre className="font-mono text-xs p-4 bg-slate-900 text-slate-100 rounded-xl whitespace-pre-wrap overflow-x-auto leading-relaxed border border-slate-800">
                      {pageDetail.markdown}
                    </pre>
                  </div>
                  <div>
                    <h5 className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1">
                      Plain Text ({pageDetail.char_count} chars)
                    </h5>
                    <pre className="font-sans text-xs p-4 bg-slate-50 text-slate-700 rounded-xl whitespace-pre-wrap overflow-x-auto leading-relaxed border border-slate-200">
                      {pageDetail.plain_text}
                    </pre>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Footer Navigation Bar */}
        <div className="px-5 py-3 border-t border-slate-200 bg-white flex items-center justify-between flex-shrink-0">
          <div className="text-xs text-slate-500">
            {pageDetail && (
              <span>
                Page character count: <strong>{pageDetail.char_count.toLocaleString()}</strong> characters
              </span>
            )}
          </div>

          {/* Prev / Next & Jump to Page */}
          <div className="flex items-center space-x-3">
            <button
              onClick={handlePrev}
              disabled={currentPage <= 1 || loadingPage}
              className="inline-flex items-center space-x-1 px-3 py-1.5 rounded-lg text-xs font-semibold bg-white border border-slate-300 text-slate-700 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-2xs"
            >
              <ChevronLeft className="w-4 h-4" />
              <span>Previous</span>
            </button>

            <form onSubmit={handleJumpSubmit} className="flex items-center space-x-1.5 text-xs text-slate-600">
              <span>Page</span>
              <input
                type="number"
                min={1}
                max={totalPages}
                value={jumpInput}
                onChange={(e) => setJumpInput(e.target.value)}
                onBlur={() => setJumpInput(String(currentPage))}
                className="w-14 px-2 py-1 text-center font-semibold text-slate-800 bg-white border border-slate-300 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-500 text-xs"
              />
              <span>of {totalPages}</span>
            </form>

            <button
              onClick={handleNext}
              disabled={currentPage >= totalPages || loadingPage}
              className="inline-flex items-center space-x-1 px-3 py-1.5 rounded-lg text-xs font-semibold bg-white border border-slate-300 text-slate-700 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-2xs"
            >
              <span>Next</span>
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
