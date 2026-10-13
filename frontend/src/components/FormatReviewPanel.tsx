import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import {
  getFormatReviewApi,
  listFormatTemplatesApi,
  runFormatReviewApi,
  type FormatReviewResponse,
  type FormatTemplateInfo,
} from '../lib/paperTools';

// Same reasoning as SummaryPanel's poll interval: this is a multi-call
// background task (several LLM calls per review), not a quick status flip.
const POLL_INTERVAL_MS = 8000;

const SEVERITY_ORDER = ['missing', 'issue', 'suggestion'] as const;

const SEVERITY_LABEL: Record<string, string> = {
  missing: 'Missing',
  issue: 'Issue',
  suggestion: 'Suggestion',
};

const SEVERITY_STYLE: Record<string, string> = {
  missing: 'border-rose-200 bg-rose-50 text-rose-700',
  issue: 'border-amber-200 bg-amber-50 text-amber-700',
  suggestion: 'border-slate-200 bg-slate-50 text-slate-600',
};

type FormatReviewPanelProps = {
  paperId: string;
  isPaperReady: boolean;
  lang: string | null;
};

export default function FormatReviewPanel({ paperId, isPaperReady, lang }: FormatReviewPanelProps) {
  const { token } = useAuth();
  const [templates, setTemplates] = useState<FormatTemplateInfo[]>([]);
  const [templateId, setTemplateId] = useState('imrad');
  const [review, setReview] = useState<FormatReviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!token) return;
    listFormatTemplatesApi(token)
      .then((result) => {
        setTemplates(result);
        if (result.length > 0 && !result.some((template) => template.id === templateId)) {
          setTemplateId(result[0].id);
        }
      })
      .catch(() => {
        // Fall back to the default template id if this fails — the review
        // endpoint still validates it server-side.
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  async function load() {
    if (!token || !isPaperReady) return;
    setError('');
    try {
      const result = await getFormatReviewApi(token, paperId, templateId, false, lang);
      setReview(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load the format review');
    } finally {
      setLoading(false);
    }
  }

  async function runReview() {
    if (!token || !isPaperReady) return;
    setRunning(true);
    setError('');
    try {
      const result = await runFormatReviewApi(token, paperId, templateId, lang);
      setReview(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start the format review');
    } finally {
      setRunning(false);
    }
  }

  useEffect(() => {
    setLoading(true);
    setReview(null);
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, paperId, isPaperReady, templateId, lang]);

  useEffect(() => {
    if (!token || !isPaperReady) return;
    const isGenerating = review?.status === 'pending' || review?.status === 'generating';
    const isTranslating = review?.translation_status === 'pending' || review?.translation_status === 'generating';
    if (!isGenerating && !isTranslating) return;

    const intervalId = window.setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => window.clearInterval(intervalId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, paperId, isPaperReady, templateId, lang, review?.status, review?.translation_status]);

  if (!isPaperReady) {
    return (
      <div className="grid h-full place-items-center px-5 text-center text-sm text-slate-500">
        The format review will be available once this paper finishes processing.
      </div>
    );
  }

  const isGenerating = review?.status === 'pending' || review?.status === 'generating';
  const translatedTextClass = review && review.language !== 'en' ? 'translated-text' : '';
  const groupedFindings = SEVERITY_ORDER.map((severity) => ({
    severity,
    items: (review?.findings ?? []).filter((finding) => finding.severity === severity),
  })).filter((group) => group.items.length > 0);

  return (
    <div className="flex h-full flex-col gap-6 overflow-y-auto px-5 py-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <label htmlFor="format-template" className="text-xs font-medium uppercase tracking-[0.1em] text-slate-500">
            Template
          </label>
          <select
            id="format-template"
            value={templateId}
            onChange={(event) => setTemplateId(event.target.value)}
            className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-700 outline-none focus:border-brand-500"
          >
            {(templates.length > 0 ? templates : [{ id: 'imrad', name: 'Generic IMRaD', description: '' }]).map(
              (template) => (
                <option key={template.id} value={template.id}>
                  {template.name}
                </option>
              ),
            )}
          </select>
        </div>
        <button
          type="button"
          onClick={() => void runReview()}
          disabled={running || isGenerating}
          className="rounded-full border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {running ? 'Starting...' : review?.status === 'failed' ? 'Try again' : 'Run review'}
        </button>
      </div>

      <p className="text-xs text-slate-400">
        Checks this paper's structure against a standard template, and asks the AI for a few quality notes — grounded
        only in your own paper's text. Everything runs locally; nothing is sent anywhere else.
      </p>

      {loading && !review ? (
        <div className="grid flex-1 place-items-center text-sm text-slate-500">Loading...</div>
      ) : error ? (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>
      ) : review ? (
        <>
          {review.status === 'failed' && (
            <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              {review.error || 'Something went wrong running the format review.'}
            </div>
          )}

          {isGenerating && (
            <div className="flex items-center gap-2 rounded-xl border border-brand-100 bg-brand-50 px-4 py-3 text-sm text-brand-700">
              <span className="flex gap-1">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-500" />
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-500 [animation-delay:150ms]" />
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-500 [animation-delay:300ms]" />
              </span>
              Checking structure and reading each section — this can take a minute or two.
            </div>
          )}

          {review.checklist.length > 0 && (
            <section>
              <h3 className="mb-2 text-sm font-semibold text-slate-900">Section checklist</h3>
              <div className="grid gap-1.5 sm:grid-cols-2">
                {review.checklist.map((item) => (
                  <div
                    key={item.id}
                    className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
                  >
                    <span className="flex items-center gap-2 text-slate-700">
                      <span
                        className={
                          item.present ? 'text-emerald-500' : item.required ? 'text-rose-500' : 'text-slate-300'
                        }
                      >
                        {item.present ? '✓' : '✕'}
                      </span>
                      {item.name}
                      {!item.required && <span className="text-xs text-slate-400">(optional)</span>}
                    </span>
                    {item.page_start != null && (
                      <span className="shrink-0 text-xs text-slate-400">
                        {item.page_start === item.page_end ? `p. ${item.page_start}` : `pp. ${item.page_start}-${item.page_end}`}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </section>
          )}

          {groupedFindings.length > 0 ? (
            <section className="space-y-4">
              <h3 className="text-sm font-semibold text-slate-900">Findings</h3>
              {groupedFindings.map((group) => (
                <div key={group.severity} className="space-y-2">
                  <p className="text-xs font-medium uppercase tracking-wide text-slate-400">
                    {SEVERITY_LABEL[group.severity]} ({group.items.length})
                  </p>
                  {group.items.map((finding, index) => (
                    <article
                      key={`${group.severity}-${index}`}
                      className={`rounded-xl border px-4 py-3 text-sm ${SEVERITY_STYLE[group.severity]}`}
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className={`font-medium ${translatedTextClass}`}>{finding.section}</span>
                        {finding.page != null && <span className="text-xs opacity-70">page {finding.page}</span>}
                      </div>
                      <p className={`mt-1 leading-6 ${translatedTextClass}`}>{finding.message}</p>
                      {finding.fix && <p className={`mt-1 text-xs opacity-80 ${translatedTextClass}`}>Fix: {finding.fix}</p>}
                    </article>
                  ))}
                </div>
              ))}
            </section>
          ) : (
            review.status === 'ready' && (
              <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
                No issues found against this template.
              </div>
            )
          )}
        </>
      ) : null}
    </div>
  );
}
