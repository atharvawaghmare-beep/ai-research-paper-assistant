import { FormEvent, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import CitationList from './CitationList';
import { explainConceptApi, type ConceptExplanationResponse, type Difficulty } from '../lib/paperTools';

const DIFFICULTIES: { value: Difficulty; label: string }[] = [
  { value: 'beginner', label: 'Beginner' },
  { value: 'intermediate', label: 'Intermediate' },
  { value: 'expert', label: 'Expert' },
];

type ConceptExplainPanelProps = {
  paperId: string;
  isPaperReady: boolean;
};

export default function ConceptExplainPanel({ paperId, isPaperReady }: ConceptExplainPanelProps) {
  const { token } = useAuth();
  const [term, setTerm] = useState('');
  const [difficulty, setDifficulty] = useState<Difficulty>('intermediate');
  const [results, setResults] = useState<ConceptExplanationResponse[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const canSubmit = Boolean(isPaperReady && token && term.trim() && !submitting);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit || !token) return;

    setSubmitting(true);
    setError('');

    try {
      const result = await explainConceptApi(token, paperId, term.trim(), difficulty);
      setResults((current) => [result, ...current]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate an explanation');
    } finally {
      setSubmitting(false);
    }
  }

  if (!isPaperReady) {
    return (
      <div className="grid h-full place-items-center px-5 text-center text-sm text-slate-500">
        Concept explanations will be available once this paper finishes processing.
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto px-5 py-6">
      <form onSubmit={handleSubmit} className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div>
          <label className="mb-1.5 block text-xs font-medium uppercase tracking-[0.1em] text-slate-500" htmlFor="concept-term">
            Term or phrase
          </label>
          <input
            id="concept-term"
            type="text"
            value={term}
            onChange={(event) => setTerm(event.target.value)}
            placeholder="e.g. self-attention, batch normalization..."
            className="w-full rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
          />
        </div>

        <div>
          <p className="mb-1.5 text-xs font-medium uppercase tracking-[0.1em] text-slate-500">Difficulty</p>
          <div className="flex flex-wrap gap-2">
            {DIFFICULTIES.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => setDifficulty(option.value)}
                className={[
                  'rounded-full px-4 py-1.5 text-sm font-medium transition',
                  difficulty === option.value
                    ? 'bg-brand-600 text-white'
                    : 'border border-slate-300 bg-white text-slate-600 hover:bg-slate-100',
                ].join(' ')}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>

        <button
          type="submit"
          disabled={!canSubmit}
          className="w-full rounded-full bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? 'Explaining...' : 'Explain'}
        </button>
      </form>

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>
      )}

      {submitting && (
        <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-500">
          <span className="flex gap-1">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-500" />
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-500 [animation-delay:150ms]" />
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-500 [animation-delay:300ms]" />
          </span>
          Thinking...
        </div>
      )}

      {results.length === 0 && !submitting ? (
        <div className="grid flex-1 place-items-center text-center">
          <div className="max-w-sm">
            <p className="text-sm font-medium text-slate-800">Explain any term from this paper</p>
            <p className="mt-2 text-sm text-slate-500">
              Enter a word or phrase and pick a difficulty level — explanations are grounded in the paper's actual content.
            </p>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          {results.map((result, index) => (
            <article key={`${result.term}-${result.difficulty}-${index}`} className="rounded-xl border border-slate-200 bg-white p-4 shadow-card">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-medium text-slate-900">“{result.term}”</p>
                <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium uppercase tracking-[0.1em] text-slate-500">
                  {result.difficulty}
                </span>
              </div>
              <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-700">{result.explanation}</p>
              <CitationList citations={result.citations} idPrefix={`explain-${index}`} />
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
