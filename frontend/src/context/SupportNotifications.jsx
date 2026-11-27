import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";

const SupportNotificationsContext = createContext({ count: 0, refresh: () => {} });

export function canUseSupport(user, staff) {
  return staff
    ? user?.user_type === "staff" && ["admin", "super_admin"].includes(user.role)
    : user?.user_type === "restaurant" && ["admin", "manager"].includes(user.role);
}

export function useSupportPolling(poll, interval = 30_000) {
  useEffect(() => {
    const refreshWhenVisible = () => {
      if (document.visibilityState !== "hidden") poll();
    };
    const timer = window.setInterval(refreshWhenVisible, interval);
    window.addEventListener("focus", refreshWhenVisible);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", refreshWhenVisible);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [poll, interval]);
}

export function SupportNotificationsProvider({ children }) {
  const { user } = useAuth();
  const scope = canUseSupport(user, true) ? "/hub/support" : canUseSupport(user, false) ? "/portal/support" : null;
  const key = scope ? `${scope}:${user.id}` : null;
  const [result, setResult] = useState(null);
  const request = useRef(null);

  const refresh = useCallback(async () => {
    if (!scope) return;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    try {
      const { data } = await api.get(`${scope}/unread`, { signal: controller.signal });
      if (!controller.signal.aborted) setResult({ key, count: data.count });
    } catch {
      // A temporary polling failure must not interrupt navigation.
    }
  }, [key, scope]);

  useEffect(() => {
    void refresh();
    return () => request.current?.abort();
  }, [refresh]);
  useSupportPolling(refresh);

  const count = result?.key === key ? result?.count ?? 0 : 0;
  return <SupportNotificationsContext.Provider value={{ count, refresh }}>{children}</SupportNotificationsContext.Provider>;
}

export const useSupportNotifications = () => useContext(SupportNotificationsContext);

export function SupportUnreadBadge({ count }) {
  if (!count) return null;
  return (
    <span
      className="rounded-full bg-[var(--dh-accent)] px-1.5 text-[10px] font-bold leading-4 text-[#0A0A09]"
      aria-label={`${count} chamados com novidades`}
      data-testid="support-unread-count"
    >
      {count > 99 ? "99+" : count}
    </span>
  );
}
