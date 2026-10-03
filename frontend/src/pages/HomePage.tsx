import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { useAuth } from '../context/AuthContext';

// Shared animation variants -------------------------------------------------

const fadeUp = {
  hidden: { opacity: 0, y: 24 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: [0.22, 1, 0.36, 1] } },
};

const staggerContainer = {
  hidden: {},
  show: {
    transition: { staggerChildren: 0.12, delayChildren: 0.05 },
  },
};

const scaleIn = {
  hidden: { opacity: 0, scale: 0.9 },
  show: { opacity: 1, scale: 1, transition: { duration: 0.4, ease: [0.22, 1, 0.36, 1] } },
};

// Viewport settings so sections only animate once, a bit before they're fully visible
const viewportOnce = { once: true, amount: 0.25 };

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
        <motion.div
          className="space-y-6"
          initial="hidden"
          animate="show"
          variants={staggerContainer}
        >
          <motion.p variants={fadeUp} className="text-sm font-medium uppercase tracking-[0.2em] text-brand-600">
            AI research paper assistant
          </motion.p>
          <motion.h1 variants={fadeUp} className="text-4xl font-semibold tracking-tight text-slate-900 sm:text-5xl">
            Upload a paper, ask it anything.
          </motion.h1>
          <motion.p variants={fadeUp} className="max-w-xl text-lg leading-8 text-slate-600">
            Marginal reads your research papers so you don't have to start from page one. Ask questions, get
            summaries, and understand difficult concepts — every answer grounded in the paper's own text and cited
            by page.
          </motion.p>
          <motion.div variants={fadeUp} className="flex flex-wrap gap-3 pt-2">
            <Link to={isAuthenticated ? '/dashboard' : '/signup'}>
              <motion.span
                whileHover={{ scale: 1.03 }}
                whileTap={{ scale: 0.97 }}
                className="inline-flex rounded-full bg-brand-600 px-6 py-3 text-sm font-semibold text-white transition hover:bg-brand-700"
              >
                {isAuthenticated ? 'Go to dashboard' : 'Get started'}
              </motion.span>
            </Link>
            {!isAuthenticated && (
              <Link to="/login">
                <motion.span
                  whileHover={{ scale: 1.03 }}
                  whileTap={{ scale: 0.97 }}
                  className="inline-flex rounded-full border border-slate-300 px-6 py-3 text-sm font-semibold text-slate-700 transition hover:border-slate-400 hover:bg-slate-50"
                >
                  Log in
                </motion.span>
              </Link>
            )}
          </motion.div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 24, scale: 0.97 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.6, delay: 0.15, ease: [0.22, 1, 0.36, 1] }}
          className="rounded-3xl border border-slate-200 bg-slate-50 p-6 shadow-panel"
        >
          <div className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-card">
            <div className="flex items-start justify-between gap-3">
              <p className="text-sm font-medium text-slate-500">You asked</p>
            </div>
            <p className="text-sm leading-6 text-slate-800">
              "What optimizer did the authors use, and what were its hyperparameters?"
            </p>
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.7, ease: [0.22, 1, 0.36, 1] }}
              className="rounded-xl bg-slate-50 p-4"
            >
              <p className="text-sm leading-6 text-slate-700">
                The authors used the Adam optimizer, with &beta;&#8321; = 0.9, &beta;&#8322; = 0.98, and &epsilon; = 10&#8315;&#8313;.
              </p>
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.4, delay: 1.1 }}
                className="mt-3 flex gap-2"
              >
                <span className="rounded-full border border-brand-100 bg-brand-50 px-2.5 py-1 text-xs font-medium text-brand-700">
                  Source 1, page 7
                </span>
              </motion.div>
            </motion.div>
          </div>
        </motion.div>
      </section>

      <motion.section
        className="space-y-10"
        initial="hidden"
        whileInView="show"
        viewport={viewportOnce}
        variants={staggerContainer}
      >
        <motion.div variants={fadeUp} className="max-w-2xl space-y-3">
          <h2 className="text-2xl font-semibold text-slate-900">Everything grounded, nothing made up</h2>
          <p className="text-slate-600">
            Marginal only answers from what's actually in the paper — and always shows you where.
          </p>
        </motion.div>
        <div className="grid gap-6 sm:grid-cols-2">
          {features.map((feature) => (
            <motion.article
              key={feature.title}
              variants={fadeUp}
              whileHover={{ y: -4 }}
              transition={{ type: 'spring', stiffness: 300, damping: 22 }}
              className="rounded-2xl border border-slate-200 bg-white p-6 shadow-card"
            >
              <h3 className="text-base font-semibold text-slate-900">{feature.title}</h3>
              <p className="mt-2 text-sm leading-6 text-slate-600">{feature.description}</p>
            </motion.article>
          ))}
        </div>
      </motion.section>

      <motion.section
        className="rounded-3xl border border-slate-200 bg-slate-50 p-8 sm:p-10"
        initial="hidden"
        whileInView="show"
        viewport={viewportOnce}
        variants={staggerContainer}
      >
        <motion.div variants={fadeUp} className="max-w-2xl space-y-3">
          <h2 className="text-2xl font-semibold text-slate-900">How it works</h2>
        </motion.div>
        <div className="mt-8 grid gap-8 sm:grid-cols-3">
          {steps.map((step, index) => (
            <motion.div key={step.title} variants={fadeUp} className="space-y-2">
              <motion.span
                variants={scaleIn}
                className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-brand-600 text-sm font-semibold text-white"
              >
                {index + 1}
              </motion.span>
              <h3 className="text-base font-semibold text-slate-900">{step.title}</h3>
              <p className="text-sm leading-6 text-slate-600">{step.description}</p>
            </motion.div>
          ))}
        </div>
      </motion.section>

      <motion.section
        className="rounded-3xl bg-slate-900 px-8 py-14 text-center sm:px-16"
        initial={{ opacity: 0, y: 24 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={viewportOnce}
        transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
      >
        <h2 className="text-2xl font-semibold text-white sm:text-3xl">Ready to stop skimming?</h2>
        <p className="mx-auto mt-3 max-w-md text-slate-300">
          Upload your first paper and ask it a question in under a minute.
        </p>
        <Link to={isAuthenticated ? '/dashboard' : '/signup'}>
          <motion.span
            whileHover={{ scale: 1.03 }}
            whileTap={{ scale: 0.97 }}
            className="mt-6 inline-flex rounded-full bg-white px-6 py-3 text-sm font-semibold text-slate-900 transition hover:bg-slate-100"
          >
            {isAuthenticated ? 'Go to dashboard' : 'Create a free account'}
          </motion.span>
        </Link>
      </motion.section>
    </div>
  );
}
