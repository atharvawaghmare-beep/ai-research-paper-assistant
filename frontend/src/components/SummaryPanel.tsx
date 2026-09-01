import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { getPaperSummaryApi, type PaperSummaryResponse } from '../lib/paperTools';

function timeAgo(iso: string): string {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? '' : 's'} ago`;
}

type SummaryPanelProps = {
  paperId: string;
  isPaperReady: boolean;
};

export default function SummaryPanel({ paperId, isPaperReady }: SummaryPanelProps) {
  const { token } = useAuth();
  const [summary, setSummary] = useState<PaperSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [regenerating, setRegenerating] = useState(false);
  const [error, setError] = useState('');

  async function load(refresh = false) {
    if (!token || !isPaperReady) return;
    if (refresh) {
      setRegenerating(true);
    } else {
      setLoading(true);
    }
    setError('');

    try {
      const result = await getPaperSummaryApi(token, paperId, refresh);
      setSummary(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load the summary');
    } finally {
      setLoading(false);
      setRegenerating(false);
    }
  }

  useEffect(() => {
    void load();
    // Re-fetch only when the paper becomes ready or identity changes — not on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, paperId, isPaperReady]);

  if (!isPaperReady) {
    return (
      <div className="grid h-full place-items-center px-5 text-center text-sm text-slate-500">
        The summary will be available once this paper finishes processing.
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto px-5 py-6">
      {loading ? (
        <div className="grid flex-1 place-items-center">
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <span className="flex gap-1">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-500" />
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-500 [animation-delay:150ms]" />
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-500 [animation-delay:300ms]" />
            </span>
            Generating summary — this can take a minute on the first run...
          </div>
        </div>
      ) : error ? (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>
      ) : summary ? (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs font-medium uppercase tracking-[0.15em] text-slate-500">
              {summary.cached ? 'Cached summary' : 'Freshly generated'}
              {summary.generated_at ? ` · ${timeAgo(summary.generated_at)}` : ''}
            </p>
            <button
              type="button"
              onClick={() => void load(true)}
              disabled={regenerating}
              className="rounded-full border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {regenerating ? 'Regenerating...' : 'Regenerate'}
            </button>
          </div>
          <div className="whitespace-pre-wrap rounded-xl border border-slate-200 bg-slate-50 px-5 py-4 text-sm leading-6 text-slate-700">
            {summary.summary}
          </div>
        </>
      ) : null}
    </div>
  );
}
