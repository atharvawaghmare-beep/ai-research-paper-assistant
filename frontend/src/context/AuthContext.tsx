import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { currentUserApi, getStoredToken, loginApi, logoutApi, signupApi, storeToken, type AuthUser } from '../lib/auth';

type AuthState = {
  user: AuthUser | null;
  token: string | null;
  loading: boolean;
};

type AuthContextValue = AuthState & {
  isAuthenticated: boolean;
  login: (payload: { email: string; password: string }) => Promise<void>;
  signup: (payload: { email: string; password: string; full_name?: string | null }) => Promise<void>;
  logout: () => Promise<void>;
  setAuthFromToken: (token: string, user: AuthUser) => void;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ user: null, token: null, loading: true });

  useEffect(() => {
    const token = getStoredToken();

    if (!token) {
      setState({ user: null, token: null, loading: false });
      return;
    }

    currentUserApi(token)
      .then((user) => {
        setState({ user, token, loading: false });
      })
      .catch(() => {
        storeToken(null);
        setState({ user: null, token: null, loading: false });
      });
  }, []);

  async function login(payload: { email: string; password: string }) {
    const response = await loginApi(payload);
    storeToken(response.token.access_token);
    setState({ user: response.user, token: response.token.access_token, loading: false });
  }

  async function signup(payload: { email: string; password: string; full_name?: string | null }) {
    const response = await signupApi(payload);
    storeToken(response.token.access_token);
    setState({ user: response.user, token: response.token.access_token, loading: false });
  }

  async function logout() {
    if (state.token) {
      try {
        await logoutApi(state.token);
      } catch {
        // Clear local session even if the server token revocation request fails.
      }
    }

    storeToken(null);
    setState({ user: null, token: null, loading: false });
  }

  function setAuthFromToken(token: string, user: AuthUser) {
    storeToken(token);
    setState({ user, token, loading: false });
  }

  const value: AuthContextValue = {
    ...state,
    isAuthenticated: Boolean(state.user && state.token),
    login,
    signup,
    logout,
    setAuthFromToken,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
}