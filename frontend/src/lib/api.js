import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API_BASE = `${BACKEND_URL}/api`;

export const api = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
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
      // sessão não recuperável: navegação full-page limpa todo o estado React
      if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
        window.location.href = "/login";
      }
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
