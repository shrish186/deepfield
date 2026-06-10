import { useCallback, useEffect, useState } from "react";
import {
  login as apiLogin,
  signup as apiSignup,
  getMe,
} from "../api";

const TOKEN_KEY = "deepfield_token";
const USER_KEY = "deepfield_user";

// Lightweight auth state backed by localStorage. The app stays usable while
// signed out (auth is optional), so this never blocks rendering — it just
// tracks the current user and exposes login/signup/logout.
export function useAuth() {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState(() => {
    try {
      const raw = localStorage.getItem(USER_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  });

  const persist = useCallback((nextToken, nextUser) => {
    if (nextToken) {
      localStorage.setItem(TOKEN_KEY, nextToken);
      localStorage.setItem(USER_KEY, JSON.stringify(nextUser));
    } else {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
    }
    setToken(nextToken || null);
    setUser(nextUser || null);
  }, []);

  // Re-validate a stored token on load; clear it silently if it's stale.
  useEffect(() => {
    if (!token) return;
    let alive = true;
    getMe(token)
      .then((fresh) => {
        if (alive) persist(token, fresh);
      })
      .catch(() => {
        if (alive) persist(null, null);
      });
    // run once on mount for the initial token
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const login = useCallback(
    async (creds) => {
      const { token: t, user: u } = await apiLogin(creds);
      persist(t, u);
      return u;
    },
    [persist]
  );

  const signup = useCallback(
    async (creds) => {
      const { token: t, user: u } = await apiSignup(creds);
      persist(t, u);
      return u;
    },
    [persist]
  );

  const logout = useCallback(() => persist(null, null), [persist]);

  return { token, user, login, signup, logout };
}
