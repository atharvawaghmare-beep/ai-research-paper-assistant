import katex from 'katex';
import 'katex/dist/katex.min.css';
import { useEffect, useMemo, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import {
  getPaperSummaryApi,
  getSectionTranslationApi,
  listLanguagesApi,
  runSectionTranslationApi,
  type PaperSectionTranslationResponse,
  type PaperSummaryResponse,
} from '../lib/paperTools';

// Generation is a multi-minute background task (many LLM calls per paper), not
// a quick status flip like paper processing — 8s keeps well under the
// endpoint's 30/minute rate limit even with other incidental calls in the
// same window, where 3s (fine for the fast paper-processing poll elsewhere)
// would exceed it and the UI would see 429s instead of progress.
const POLL_INTERVAL_MS = 8000;

function timeAgo(iso: string): string {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? '' : 's'} ago`;
}

function pageLabel(start: number, end: number): string {
  return start === end ? `p. ${start}` : `pp. ${start}-${end}`;
}

function sectionAnchorId(index: number): string {
  return `summary-section-${index}`;
}

// Renders an AI-reconstructed LaTeX equation via KaTeX — always alongside the
// raw extracted text and a "reconstruction" label, never in place of it (PDF
// text extraction of math is lossy; this is a best-effort re-rendering, not
// the paper's exact original formatting).
function RenderedEquation({ latex }: { latex: string }) {
  const html = useMemo(() => {
    try {
      return katex.renderToString(latex, { throwOnError: false, displayMode: true });
    } catch {
      return null;
    }
  }, [latex]);

  if (!html) return null;
  // eslint-disable-next-line react/no-danger
  return <div className="overflow-x-auto py-1" dangerouslySetInnerHTML={{ __html: html }} />;
}

type SummaryPanelProps = {
  paperId: string;
  isPaperReady: boolean;
  lang: string | null;
  // Lets controls placed inside this panel (e.g. a "Translate" button right
  // on the overall summary) change the page's shared display language —
  // the same state the top-right LanguageSelector controls — rather than
  // introducing a second, independent translation path for one card.
  onLangChange: (lang: string | null) => void;
};

export default function SummaryPanel({ paperId, isPaperReady, lang, onLangChange }: SummaryPanelProps) {
  const { token } = useAuth();
  const [summary, setSummary] = useState<PaperSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [regenerating, setRegenerating] = useState(false);
  const [error, setError] = useState('');
  const [languages, setLanguages] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!token) return;
    listLanguagesApi(token)
      .then(setLanguages)
      .catch(() => {
        // Leave empty — the overall-summary "Translate" button just won't render.
      });
  }, [token]);

  // Phase 18: "translate this section of the paper itself" — keyed by
  // outline index, independent of (and in addition to) the generated
  // summary's own translation above.
  const [sectionTranslations, setSectionTranslations] = useState<Record<number, PaperSectionTranslationResponse>>({});
  const [expandedSection, setExpandedSection] = useState<number | null>(null);

  async function load(refresh = false) {
    if (!token || !isPaperReady) return;
    if (refresh) {
      setRegenerating(true);
    } else if (!summary) {
      setLoading(true);
    }
    setError('');

    try {
      const result = await getPaperSummaryApi(token, paperId, refresh, lang);
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
    // Re-fetch when the paper becomes ready, identity changes, or the
    // selected display language changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, paperId, isPaperReady, lang]);

  // Poll while generation is in progress, same pattern as paper-processing
  // status elsewhere in the app — this is a background task (many LLM calls
  // per paper), not a request the frontend waits on. Also polls while a
  // requested translation is still being generated.
  useEffect(() => {
    if (!token || !isPaperReady) return;
    const isGenerating = summary?.status === 'pending' || summary?.status === 'generating';
    const isTranslating = summary?.translation_status === 'pending' || summary?.translation_status === 'generating';
    if (!isGenerating && !isTranslating) return;

    const intervalId = window.setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => window.clearInterval(intervalId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, paperId, isPaperReady, lang, summary?.status, summary?.translation_status]);

  async function translateSection(index: number) {
    if (!token || !lang) return;
    setExpandedSection(index);
    try {
      const result = await runSectionTranslationApi(token, paperId, index, lang);
      setSectionTranslations((current) => ({ ...current, [index]: result }));
    } catch (err) {
      setSectionTranslations((current) => ({
        ...current,
        [index]: {
          status: 'failed',
          cached: false,
          language: lang,
          section_index: index,
          heading: null,
          translated_heading: null,
          translated_text: null,
          page_start: null,
          page_end: null,
          generated_at: null,
          error: err instanceof Error ? err.message : 'Failed to translate this section',
        },
      }));
    }
  }

  // Poll any section translations still in progress.
  useEffect(() => {
    if (!token || !lang) return;
    const inProgress = Object.values(sectionTranslations).filter(
      (entry) => entry.status === 'pending' || entry.status === 'generating',
    );
    if (inProgress.length === 0) return;

    const intervalId = window.setInterval(() => {
      inProgress.forEach((entry) => {
        void getSectionTranslationApi(token, paperId, entry.section_index, lang).then((result) => {
          setSectionTranslations((current) => ({ ...current, [entry.section_index]: result }));
        });
      });
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(intervalId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, paperId, lang, sectionTranslations]);

  if (!isPaperReady) {
    return (
      <div className="grid h-full place-items-center px-5 text-center text-sm text-slate-500">
        The summary will be available once this paper finishes processing.
      </div>
    );
  }

  const isGenerating = summary?.status === 'pending' || summary?.status === 'generating';
  const isTranslated = Boolean(summary && summary.language !== 'en');
  const translatedTextClass = isTranslated ? 'translated-text' : '';

  return (
    <div className="flex h-full flex-col gap-6 overflow-y-auto px-5 py-6">
      {loading && !summary ? (
        <div className="grid flex-1 place-items-center">
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <span className="flex gap-1">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-500" />
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-500 [animation-delay:150ms]" />
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-500 [animation-delay:300ms]" />
            </span>
            Loading...
          </div>
        </div>
      ) : error ? (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>
      ) : summary ? (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs font-medium uppercase tracking-[0.15em] text-slate-500">
              {summary.status === 'ready' && summary.cached && 'Cached summary'}
              {summary.status === 'ready' && !summary.cached && 'Freshly generated'}
              {summary.status === 'generating' && 'Generating...'}
              {summary.status === 'pending' && 'Queued...'}
              {summary.status === 'failed' && 'Generation failed'}
              {summary.generated_at && summary.status === 'ready' ? ` · ${timeAgo(summary.generated_at)}` : ''}
              {summary.translation_status === 'generating' && ' · Translating...'}
              {summary.translation_status === 'failed' && ' · translation failed, showing English'}
            </p>
            <button
              type="button"
              onClick={() => void load(true)}
              disabled={regenerating || isGenerating}
              className="rounded-full border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {regenerating ? 'Regenerating...' : summary.status === 'failed' ? 'Try again' : 'Regenerate'}
            </button>
          </div>

          {summary.status === 'failed' && (
            <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              {summary.error || 'Something went wrong generating the summary.'}
            </div>
          )}

          {isGenerating && (
            <div className="flex items-center gap-2 rounded-xl border border-brand-100 bg-brand-50 px-4 py-3 text-sm text-brand-700">
              <span className="flex gap-1">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-500" />
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-500 [animation-delay:150ms]" />
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-500 [animation-delay:300ms]" />
              </span>
              Reading the paper, summarizing each section, and explaining its equations — this can take a few
              minutes on the first run.
            </div>
          )}

          {summary.outline.length > 0 && (
            <section>
              <h3 className="mb-2 text-sm font-semibold text-slate-900">Contents</h3>
              <nav className="rounded-xl border border-slate-200 bg-white px-4 py-2">
                <ol className="divide-y divide-slate-100">
                  {summary.outline.map((section, index) => (
                    <li key={`${section.heading}-${index}`}>
                      <div className="flex items-center justify-between gap-3 py-2 text-sm text-slate-700">
                        <a href={`#${sectionAnchorId(index)}`} className="min-w-0 flex-1 truncate hover:text-brand-700">
                          {section.heading}
                        </a>
                        <span className="shrink-0 text-xs text-slate-400">
                          {pageLabel(section.page_start, section.page_end)}
                        </span>
                        {lang && (
                          <button
                            type="button"
                            onClick={() => void translateSection(index)}
                            className="shrink-0 rounded-full border border-slate-200 px-2 py-0.5 text-xs font-medium text-slate-500 transition hover:bg-slate-50"
                          >
                            Translate
                          </button>
                        )}
                      </div>

                      {expandedSection === index && sectionTranslations[index] && (
                        <div className="mb-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs">
                          {(sectionTranslations[index].status === 'pending' ||
                            sectionTranslations[index].status === 'generating') && (
                            <p className="text-slate-500">Translating this section...</p>
                          )}
                          {sectionTranslations[index].status === 'failed' && (
                            <p className="text-rose-600">{sectionTranslations[index].error || 'Translation failed.'}</p>
                          )}
                          {sectionTranslations[index].status === 'ready' && (
                            <div className="translated-text space-y-1 text-sm leading-6 text-slate-700">
                              <p className="font-medium text-slate-900">
                                {sectionTranslations[index].translated_heading}
                              </p>
                              <p className="whitespace-pre-wrap">{sectionTranslations[index].translated_text}</p>
                            </div>
                          )}
                        </div>
                      )}
                    </li>
                  ))}
                </ol>
              </nav>
            </section>
          )}

          {summary.section_summaries.length > 0 && (
            <section className="space-y-2">
              <h3 className="text-sm font-semibold text-slate-900">Section summaries</h3>
              {summary.section_summaries.map((section, index) => (
                <details
                  key={`${section.heading}-${index}`}
                  id={sectionAnchorId(index)}
                  className="group rounded-xl border border-slate-200 bg-white px-4 py-3 scroll-mt-4"
                >
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-medium text-slate-800">
                    <span className={`truncate ${translatedTextClass}`}>{section.heading}</span>
                    <span className="flex shrink-0 items-center gap-2 text-xs font-normal text-slate-400">
                      {pageLabel(section.page_start, section.page_end)}
                      <span className="transition group-open:rotate-180">▾</span>
                    </span>
                  </summary>
                  <p className={`mt-2 text-sm leading-6 text-slate-600 ${translatedTextClass}`}>{section.summary}</p>
                </details>
              ))}
            </section>
          )}

          {summary.overall_summary && (
            <section>
              <div className="mb-2 flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold text-slate-900">Overall summary</h3>
                {Object.keys(languages).length > 0 && (
                  <button
                    type="button"
                    onClick={() => onLangChange(lang ? null : Object.keys(languages)[0])}
                    className="shrink-0 rounded-full border border-slate-200 px-2.5 py-0.5 text-xs font-medium text-slate-500 transition hover:bg-slate-50"
                  >
                    {lang
                      ? 'Show in English'
                      : `Translate to ${languages[Object.keys(languages)[0]]}`}
                  </button>
                )}
              </div>
              {summary.translation_status === 'generating' && (
                <p className="mb-2 text-xs text-slate-500">Translating...</p>
              )}
              <div
                className={`whitespace-pre-wrap rounded-xl border border-slate-200 bg-slate-50 px-5 py-4 text-sm leading-6 text-slate-700 ${translatedTextClass}`}
              >
                {summary.overall_summary}
              </div>
            </section>
          )}

          {(summary.equations.length > 0 || summary.methods.length > 0) && (
            <section className="space-y-4">
              <h3 className="text-sm font-semibold text-slate-900">Equations & methods</h3>

              {summary.methods.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {summary.methods.map((method) => (
                    <span
                      key={method}
                      className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-600"
                    >
                      {method}
                    </span>
                  ))}
                </div>
              )}

              {summary.equations.map((equation, index) => (
                <article key={index} className="rounded-xl border border-slate-200 bg-white p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-0.5 text-xs font-medium text-slate-500">
                      page {equation.page}
                    </span>
                    <span
                      className={
                        equation.confidence === 'numbered'
                          ? 'rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-700'
                          : 'rounded-full border border-amber-200 bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-700'
                      }
                      title={
                        equation.confidence === 'numbered'
                          ? 'A standalone equation number (e.g. "(3)") was found — high confidence'
                          : 'Flagged by a dense cluster of math symbols, not a numbered marker — lower confidence'
                      }
                    >
                      {equation.confidence === 'numbered' ? 'Numbered equation' : 'Possible equation'}
                    </span>
                  </div>

                  <p className="mt-2 text-xs font-medium uppercase tracking-wide text-slate-400">As extracted from the PDF</p>
                  <pre className="mt-1 overflow-x-auto whitespace-pre-wrap rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
                    {equation.raw_text}
                  </pre>

                  {equation.latex && (
                    <>
                      <p className="mt-3 text-xs font-medium uppercase tracking-wide text-slate-400">
                        AI-reconstructed (not the paper's exact formatting)
                      </p>
                      <RenderedEquation latex={equation.latex} />
                    </>
                  )}

                  <p className={`mt-3 text-sm leading-6 text-slate-700 ${translatedTextClass}`}>{equation.explanation}</p>
                </article>
              ))}
            </section>
          )}
        </>
      ) : null}
    </div>
  );
}
