import { NavLink, Outlet } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  [
    'rounded-full px-4 py-2 text-sm font-medium transition',
    isActive ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900',
  ].join(' ');

export default function AppLayout() {
  const { isAuthenticated, logout, user } = useAuth();

  return (
    <div className="flex min-h-screen flex-col bg-white">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4 sm:px-6 lg:px-8">
          <NavLink to="/" className="flex items-center gap-2">
            <span className="grid h-8 w-8 place-items-center rounded-lg bg-brand-600 text-sm font-bold text-white">
              M
            </span>
            <span className="text-lg font-semibold text-slate-900">Marginal</span>
          </NavLink>

          <nav className="flex flex-wrap items-center gap-1">
            <NavLink className={navLinkClass} to="/" end>
              Home
            </NavLink>
            {isAuthenticated ? (
              <>
                <NavLink className={navLinkClass} to="/dashboard">
                  Dashboard
                </NavLink>
                <button
                  type="button"
                  onClick={() => {
                    void logout();
                  }}
                  className="ml-1 rounded-full px-4 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-100 hover:text-slate-900"
                >
                  Log out{user?.full_name ? `, ${user.full_name}` : ''}
                </button>
              </>
            ) : (
              <>
                <NavLink className={navLinkClass} to="/login">
                  Log in
                </NavLink>
                <NavLink
                  to="/signup"
                  className="ml-1 rounded-full bg-brand-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-brand-700"
                >
                  Sign up
                </NavLink>
              </>
            )}
          </nav>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-10 sm:px-6 lg:px-8">
        <Outlet />
      </main>

      <footer className="border-t border-slate-200 py-6">
        <p className="mx-auto max-w-6xl px-4 text-sm text-slate-400 sm:px-6 lg:px-8">
          Marginal — an AI research paper assistant.
        </p>
      </footer>
    </div>
  );
}
