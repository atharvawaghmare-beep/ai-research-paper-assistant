import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import PdfUploadDropzone from '../components/PdfUploadDropzone';
import { deletePaperApi, listUploadedPapersApi, type UploadedPaper } from '../lib/auth';

const TERMINAL_STATUSES = new Set(['ready', 'failed']);
const POLL_INTERVAL_MS = 3000;

const STATUS_LABELS: Record<string, string> = {
  uploaded: 'Queued',
  chunking: 'Chunking...',
  embedding: 'Embedding...',
  ready: 'Ready',
  failed: 'Failed',
};

function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

function statusBadgeClasses(status: string): string {
  const base = 'rounded-full border px-3 py-1 text-xs font-medium';
  if (status === 'ready') {
    return `${base} border-emerald-200 bg-emerald-50 text-emerald-700`;
  }
  if (status === 'failed') {
    return `${base} border-rose-200 bg-rose-50 text-rose-700`;
  }
  if (status === 'chunking' || status === 'embedding') {
    return `${base} border-brand-100 bg-brand-50 text-brand-700 animate-pulse`;
  }
  return `${base} border-slate-200 bg-slate-50 text-slate-600`;
}

function formatSize(bytes: number | null): string {
  if (!bytes) return 'Unknown size';
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function DashboardPage() {
  const { token, user } = useAuth();
  const [uploadedPapers, setUploadedPapers] = useState<UploadedPaper[]>([]);
  const [loadingPapers, setLoadingPapers] = useState(true);
  const [papersError, setPapersError] = useState('');
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [deleteError, setDeleteError] = useState('');

  async function refreshPapers(options?: { silent?: boolean }) {
    if (!token) {
      return;
    }

    if (!options?.silent) {
      setLoadingPapers(true);
    }
    setPapersError('');

    try {
      const papers = await listUploadedPapersApi(token);
      setUploadedPapers(papers);
    } catch (error) {
      setPapersError(error instanceof Error ? error.message : 'Unable to load uploaded PDFs');
    } finally {
      setLoadingPapers(false);
    }
  }

  useEffect(() => {
    void refreshPapers();
  }, [token]);

  // While any paper is still being chunked/embedded, poll for real progress
  // instead of leaving a stale status on screen until the user manually refreshes.
  const isProcessing = uploadedPapers.some((paper) => !TERMINAL_STATUSES.has(paper.processing_status));

  useEffect(() => {
    if (!token || !isProcessing) {
      return;
    }

    const intervalId = window.setInterval(() => {
      void refreshPapers({ silent: true });
    }, POLL_INTERVAL_MS);

    return () => window.clearInterval(intervalId);
  }, [token, isProcessing]);

  const readyCount = uploadedPapers.filter((paper) => paper.processing_status === 'ready').length;

  async function handleDelete(paperId: number) {
    if (!token) return;
    setDeletingId(paperId);
    setDeleteError('');

    try {
      await deletePaperApi(token, paperId);
      setUploadedPapers((current) => current.filter((paper) => paper.id !== paperId));
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : 'Failed to delete paper');
    } finally {
      setDeletingId(null);
      setConfirmDeleteId(null);
    }
  }

  return (
    <section className="space-y-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold text-slate-900">Welcome back{user?.full_name ? `, ${user.full_name}` : ''}</h1>
        <p className="text-sm text-slate-500">
          {uploadedPapers.length === 0
            ? 'Upload your first paper to get started.'
            : `${uploadedPapers.length} paper${uploadedPapers.length === 1 ? '' : 's'} · ${readyCount} ready`}
        </p>
      </header>

      <PdfUploadDropzone onUploaded={() => void refreshPapers()} />

      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900">Your papers</h2>
          <button
            type="button"
            onClick={() => void refreshPapers()}
            className="rounded-full border border-slate-200 px-3.5 py-1.5 text-sm font-medium text-slate-600 transition hover:bg-slate-50"
          >
            Refresh
          </button>
        </div>

        {deleteError && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-sm text-rose-700">{deleteError}</div>
        )}

        <div className="divide-y divide-slate-200 rounded-2xl border border-slate-200 bg-white shadow-card">
          {loadingPapers ? (
            <div className="px-5 py-6 text-sm text-slate-500">Loading your papers...</div>
          ) : papersError ? (
            <div className="px-5 py-6 text-sm text-rose-600">{papersError}</div>
          ) : uploadedPapers.length === 0 ? (
            <div className="px-5 py-6 text-sm text-slate-500">No papers yet — use the upload panel above to add one.</div>
          ) : (
            uploadedPapers.map((paper) => (
              <article key={paper.id} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-slate-900">{paper.title}</p>
                  <p className="mt-1 text-xs text-slate-500">
                    {paper.original_filename} · {formatSize(paper.file_size_bytes)}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span className={statusBadgeClasses(paper.processing_status)}>{statusLabel(paper.processing_status)}</span>
                  <Link
                    to={`/papers/${paper.id}`}
                    className="rounded-full border border-slate-200 px-3.5 py-1.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
                  >
                    Open
                  </Link>
                  {confirmDeleteId === paper.id ? (
                    <>
                      <button
                        type="button"
                        onClick={() => void handleDelete(paper.id)}
                        disabled={deletingId === paper.id}
                        className="rounded-full bg-rose-600 px-3.5 py-1.5 text-sm font-medium text-white transition hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {deletingId === paper.id ? 'Deleting...' : 'Confirm delete'}
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmDeleteId(null)}
                        disabled={deletingId === paper.id}
                        className="rounded-full px-3.5 py-1.5 text-sm font-medium text-slate-500 transition hover:bg-slate-100"
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setConfirmDeleteId(paper.id)}
                      className="rounded-full px-3.5 py-1.5 text-sm font-medium text-slate-500 transition hover:bg-rose-50 hover:text-rose-600"
                    >
                      Delete
                    </button>
                  )}
                </div>
              </article>
            ))
          )}
        </div>
      </section>
    </section>
  );
}
