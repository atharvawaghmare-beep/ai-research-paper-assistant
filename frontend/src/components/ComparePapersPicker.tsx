import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { listUploadedPapersApi, type UploadedPaper } from '../lib/auth';

type ComparePapersPickerProps = {
  currentPaperId: string;
  selectedPaperIds: number[];
  onChange: (ids: number[]) => void;
};

export default function ComparePapersPicker({ currentPaperId, selectedPaperIds, onChange }: ComparePapersPickerProps) {
  const { token } = useAuth();
  const [candidates, setCandidates] = useState<UploadedPaper[]>([]);
  const [open, setOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;

    listUploadedPapersApi(token)
      .then((papers) => {
        if (cancelled) return;
        setCandidates(
          papers.filter((paper) => String(paper.id) !== currentPaperId && paper.processing_status === 'ready'),
        );
      })
      .catch(() => {
        // No candidates to compare against — the picker just won't render.
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });

    return () => {
      cancelled = true;
    };
  }, [token, currentPaperId]);

  if (!loaded || candidates.length === 0) {
    return null;
  }

  const selectedPapers = candidates.filter((paper) => selectedPaperIds.includes(paper.id));

  function toggle(id: number) {
    onChange(selectedPaperIds.includes(id) ? selectedPaperIds.filter((existing) => existing !== id) : [...selectedPaperIds, id]);
  }

  return (
    <div className="border-b border-slate-200 px-5 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setOpen((current) => !current)}
          className="rounded-full border border-dashed border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-brand-400 hover:text-brand-700"
        >
          + Compare with another paper
        </button>
        {selectedPapers.map((paper) => (
          <span
            key={paper.id}
            className="flex items-center gap-1.5 rounded-full border border-brand-100 bg-brand-50 px-3 py-1 text-xs font-medium text-brand-700"
          >
            {paper.title}
            <button type="button" onClick={() => toggle(paper.id)} className="text-brand-400 transition hover:text-brand-700">
              ×
            </button>
          </span>
        ))}
      </div>

      {open && (
        <div className="mt-2 flex flex-wrap gap-2 rounded-xl border border-slate-200 bg-slate-50 p-3">
          {candidates.map((paper) => (
            <button
              key={paper.id}
              type="button"
              onClick={() => toggle(paper.id)}
              className={[
                'rounded-full px-3 py-1.5 text-xs font-medium transition',
                selectedPaperIds.includes(paper.id)
                  ? 'bg-brand-600 text-white'
                  : 'border border-slate-200 bg-white text-slate-600 hover:bg-slate-100',
              ].join(' ')}
            >
              {paper.title}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
