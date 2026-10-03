import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const features = [
  {
    title: 'Ask questions, get cited answers',
    description:
      "Chat with any uploaded paper. Every answer is grounded in the paper's actual text, with expandable citations pointing to the exact page.",
  },
  {
    title: 'Instant summaries',
    description:
      'Get a clear, structured summary of a paper’s problem, approach, and results — generated once and cached, not regenerated every time you look.',
  },
  {
    title: 'Concept explanations',
    description:
      'Ask for any term or idea from the paper, explained at your level — beginner, intermediate, or expert — still grounded in the source text.',
  },
  {
    title: 'Compare across papers',
    description:
      'Bring two or more papers into one conversation and ask comparison questions — answers make clear which paper each claim comes from.',
  },
];

const steps = [
  { title: 'Upload a PDF', description: 'Drag in a research paper. We validate it, store it, and get to work.' },
  {
    title: 'We read it for you',
    description: 'The paper is split into sections, embedded, and indexed — usually ready within a minute.',
  },
  { title: 'Ask anything', description: 'Chat, request a summary, or ask for an explanation — always grounded, always cited.' },
];

export default function HomePage() {
  const { isAuthenticated } = useAuth();

  return (
    <div className="space-y-24">
      <section className="grid gap-10 pt-8 lg:grid-cols-2 lg:items-center lg:pt-16">
        <div className="space-y-6">
          <p className="text-sm font-medium uppercase tracking-[0.2em] text-brand-600">AI research paper assistant</p>
          <h1 className="text-4xl font-semibold tracking-tight text-slate-900 sm:text-5xl">
            Upload a paper, ask it anything.
          </h1>
          <p className="max-w-xl text-lg leading-8 text-slate-600">
            Marginal reads your research papers so you don't have to start from page one. Ask questions, get
            summaries, and understand difficult concepts — every answer grounded in the paper's own text and cited
            by page.
          </p>
          <div className="flex flex-wrap gap-3 pt-2">
            <Link
              to={isAuthenticated ? '/dashboard' : '/signup'}
              className="inline-flex rounded-full bg-brand-600 px-6 py-3 text-sm font-semibold text-white transition hover:bg-brand-700"
            >
              {isAuthenticated ? 'Go to dashboard' : 'Get started'}
            </Link>
            {!isAuthenticated && (
              <Link
                to="/login"
                className="inline-flex rounded-full border border-slate-300 px-6 py-3 text-sm font-semibold text-slate-700 transition hover:border-slate-400 hover:bg-slate-50"
              >
                Log in
              </Link>
            )}
          </div>
        </div>

        <div className="rounded-3xl border border-slate-200 bg-slate-50 p-6 shadow-panel">
          <div className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-card">
            <div className="flex items-start justify-between gap-3">
              <p className="text-sm font-medium text-slate-500">You asked</p>
            </div>
            <p className="text-sm leading-6 text-slate-800">
              "What optimizer did the authors use, and what were its hyperparameters?"
            </p>
            <div className="rounded-xl bg-slate-50 p-4">
              <p className="text-sm leading-6 text-slate-700">
                The authors used the Adam optimizer, with &beta;&#8321; = 0.9, &beta;&#8322; = 0.98, and &epsilon; = 10&#8315;&#8313;.
              </p>
              <div className="mt-3 flex gap-2">
                <span className="rounded-full border border-brand-100 bg-brand-50 px-2.5 py-1 text-xs font-medium text-brand-700">
                  Source 1, page 7
                </span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="space-y-10">
        <div className="max-w-2xl space-y-3">
          <h2 className="text-2xl font-semibold text-slate-900">Everything grounded, nothing made up</h2>
          <p className="text-slate-600">
            Marginal only answers from what's actually in the paper — and always shows you where.
          </p>
        </div>
        <div className="grid gap-6 sm:grid-cols-2">
          {features.map((feature) => (
            <article key={feature.title} className="rounded-2xl border border-slate-200 bg-white p-6 shadow-card">
              <h3 className="text-base font-semibold text-slate-900">{feature.title}</h3>
              <p className="mt-2 text-sm leading-6 text-slate-600">{feature.description}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="rounded-3xl border border-slate-200 bg-slate-50 p-8 sm:p-10">
        <div className="max-w-2xl space-y-3">
          <h2 className="text-2xl font-semibold text-slate-900">How it works</h2>
        </div>
        <div className="mt-8 grid gap-8 sm:grid-cols-3">
          {steps.map((step, index) => (
            <div key={step.title} className="space-y-2">
              <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-brand-600 text-sm font-semibold text-white">
                {index + 1}
              </span>
              <h3 className="text-base font-semibold text-slate-900">{step.title}</h3>
              <p className="text-sm leading-6 text-slate-600">{step.description}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-3xl bg-slate-900 px-8 py-14 text-center sm:px-16">
        <h2 className="text-2xl font-semibold text-white sm:text-3xl">Ready to stop skimming?</h2>
        <p className="mx-auto mt-3 max-w-md text-slate-300">
          Upload your first paper and ask it a question in under a minute.
        </p>
        <Link
          to={isAuthenticated ? '/dashboard' : '/signup'}
          className="mt-6 inline-flex rounded-full bg-white px-6 py-3 text-sm font-semibold text-slate-900 transition hover:bg-slate-100"
        >
          {isAuthenticated ? 'Go to dashboard' : 'Create a free account'}
        </Link>
      </section>
    </div>
  );
}
