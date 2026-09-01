import { Link } from 'react-router-dom';

export default function NotFoundPage() {
  return (
    <section className="grid min-h-[50vh] place-items-center text-center">
      <div className="space-y-4">
        <p className="text-sm font-medium uppercase tracking-[0.2em] text-brand-600">404</p>
        <h2 className="text-4xl font-semibold text-slate-900">Page not found</h2>
        <p className="text-slate-500">This page doesn't exist.</p>
        <Link
          className="inline-flex rounded-full bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-brand-700"
          to="/"
        >
          Go home
        </Link>
      </div>
    </section>
  );
}
