import { createContext, useContext, useEffect, useState, useCallback, useRef } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
import { clearTabSessionId, startNewTabSession } from "@/lib/tabSession";

const AuthContext = createContext(null);
const ACCESS_REVALIDATION_INTERVAL_MS = 60_000;
const ACCESS_ENDED_MESSAGE = "Seu acesso ao DACOT foi encerrado.";

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null); // null=loading | false=guest | object=logged
  const [error, setError] = useState(null);
  const authRequestRef = useRef(0);

  const refresh = useCallback(async ({ showAccessEndedMessage = false } = {}) => {
    const requestId = ++authRequestRef.current;
    try {
      const { data } = await api.get("/auth/me");
      if (requestId === authRequestRef.current) setUser(data);
    } catch {
      try {
        // F5 retains this tab's identifier. Renew only this tab when its
        // server-side refresh window is still valid.
        await api.post("/auth/refresh");
        const { data } = await api.get("/auth/me");
        if (requestId === authRequestRef.current) setUser(data);
      } catch (refreshError) {
        if (requestId === authRequestRef.current) {
          if (showAccessEndedMessage && refreshError.response?.status === 401) {
            setError(ACCESS_ENDED_MESSAGE);
          }
          setUser(false);
        }
      }
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    if (!user || user === false) return undefined;

    const revalidateAccess = () => refresh({ showAccessEndedMessage: true });
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") revalidateAccess();
    };
    const intervalId = window.setInterval(revalidateAccess, ACCESS_REVALIDATION_INTERVAL_MS);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      window.clearInterval(intervalId);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [refresh, user]);

  const login = async (email, password) => {
    authRequestRef.current += 1;
    setError(null);
    try {
      // Explicit login always gets a new opaque identity for this tab.
      startNewTabSession();
      const { data } = await api.post("/auth/login", { email, password });
      setUser(data);
      return data;
    } catch (e) {
      setError(formatApiErrorDetail(e.response?.data?.detail) || e.message);
      return false;
    }
  };

  const logout = useCallback(async () => {
    authRequestRef.current += 1;
    setUser(false);
    try { await api.post("/auth/logout"); } catch { /* ignore */ }
    clearTabSessionId();
  }, []);

  const beginFreshEntry = useCallback(() => {
    authRequestRef.current += 1;
    startNewTabSession();
    setUser(false);
    setError(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, error, setError, login, logout, refresh, beginFreshEntry }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
