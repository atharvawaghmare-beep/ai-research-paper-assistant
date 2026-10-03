import { FormEvent, useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { validateLoginForm } from '../lib/validation';

type LocationState = {
  from?: {
    pathname?: string;
  };
};

export default function LoginPage() {
  const { login, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  if (isAuthenticated) {
    const state = location.state as LocationState | null;
    return <Navigate to={state?.from?.pathname ?? '/dashboard'} replace />;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextErrors = validateLoginForm({ email, password });
    setErrors(nextErrors);

    if (Object.keys(nextErrors).length > 0) {
      return;
    }

    setSubmitting(true);
    setFormError('');

    try {
      await login({ email, password });
      const state = location.state as LocationState | null;
      navigate(state?.from?.pathname ?? '/dashboard', { replace: true });
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'Unable to sign in');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="mx-auto max-w-sm space-y-6 py-8">
      <div className="space-y-1 text-center">
        <h2 className="text-2xl font-semibold text-slate-900">Welcome back</h2>
        <p className="text-sm text-slate-500">Sign in to continue to your papers.</p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-card">
        <div>
          <label className="mb-1.5 block text-sm font-medium text-slate-700" htmlFor="email">
            Email
          </label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
            placeholder="you@example.com"
          />
          {errors.email && <p className="mt-1.5 text-sm text-rose-600">{errors.email}</p>}
        </div>

        <div>
          <label className="mb-1.5 block text-sm font-medium text-slate-700" htmlFor="password">
            Password
          </label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
            placeholder="Enter your password"
          />
          {errors.password && <p className="mt-1.5 text-sm text-rose-600">{errors.password}</p>}
        </div>

        {formError && (
          <p className="rounded-xl border border-rose-200 bg-rose-50 px-3.5 py-2.5 text-sm text-rose-700">{formError}</p>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-full bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? 'Signing in...' : 'Sign in'}
        </button>

        <p className="text-center text-sm text-slate-500">
          Need an account?{' '}
          <Link className="font-medium text-brand-600 hover:text-brand-700" to="/signup">
            Create one
          </Link>
        </p>
      </form>
    </section>
  );
}
