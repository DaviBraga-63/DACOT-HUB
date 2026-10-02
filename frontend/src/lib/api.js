import axios from "axios";
import { clearTabSessionId, getTabSessionId } from "@/lib/tabSession";

const configuredBackendUrl = process.env.REACT_APP_BACKEND_URL?.trim().replace(/\/+$/, "");

// In the combined production deployment, requests stay on the current origin.
// A configured URL remains available for the existing separate local frontend
// and backend workflow.
export const API_BASE = configuredBackendUrl ? `${configuredBackendUrl}/api` : "/api";

export const api = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
});

api.interceptors.request.use((config) => {
  // The UUID alone is not an authentication credential. The backend also
  // requires a matching HttpOnly browser binding and live Mongo session.
  config.headers = config.headers || {};
  config.headers["X-DACOT-Tab-Session"] = getTabSessionId();
  return config;
});

const AUTH_PATHS = [
  "/auth/login",
  "/auth/logout",
  "/auth/refresh",
  "/auth/forgot-password",
  "/auth/reset-password",
  "/auth/me",
];

let refreshPromise = null;

function navigateToLogin() {
  if (typeof window === "undefined" || window.location.pathname === "/login") return;

  // Keep this redirect inside the SPA. A full-page navigation to /login makes
  // the hosting server resolve that path and can produce its own 404 response.
  window.history.replaceState(window.history.state, "", "/login");
  window.dispatchEvent(new PopStateEvent("popstate"));
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;
    const status = error.response?.status;
    const url = original?.url || "";
    const isAuthRoute = AUTH_PATHS.some((p) => url.includes(p));

    if (status !== 401 || isAuthRoute || !original || original._retried) {
      return Promise.reject(error);
    }
    original._retried = true;

    try {
      // single-flight: 401s concorrentes aguardam o mesmo refresh
      if (!refreshPromise) {
        refreshPromise = api
          .post("/auth/refresh")
          .finally(() => { refreshPromise = null; });
      }
      await refreshPromise;
      return api(original);
    } catch (refreshError) {
      // Sessão não recuperável: navegue sem recarregar a página para manter a
      // resolução da rota no React Router, e não no servidor de hospedagem.
      clearTabSessionId();
      navigateToLogin();
      return Promise.reject(refreshError);
    }
  }
);

export function formatApiErrorDetail(detail) {
  if (detail == null) return "Algo deu errado. Tente novamente.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail
      .map((e) => (e && typeof e.msg === "string" ? e.msg : JSON.stringify(e)))
      .filter(Boolean)
      .join(" ");
  if (detail && typeof detail.msg === "string") return detail.msg;
  return String(detail);
}
