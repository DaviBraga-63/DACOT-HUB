import { createContext, useContext, useEffect, useState, useCallback, useRef } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null); // null=loading | false=guest | object=logged
  const [error, setError] = useState(null);
  const authRequestRef = useRef(0);

  const refresh = useCallback(async () => {
    const requestId = ++authRequestRef.current;
    try {
      const { data } = await api.get("/auth/me");
      if (requestId === authRequestRef.current) setUser(data);
    } catch {
      if (requestId === authRequestRef.current) setUser(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const login = async (email, password) => {
    authRequestRef.current += 1;
    setError(null);
    try {
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
  }, []);

  return (
    <AuthContext.Provider value={{ user, error, setError, login, logout, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
