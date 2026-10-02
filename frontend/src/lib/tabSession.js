const TAB_SESSION_STORAGE_KEY = "dacot.tab-session-id";

function createSecureTabId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  throw new Error("Este navegador não oferece geração criptográfica para a sessão da aba.");
}

export function getTabSessionId() {
  const existing = sessionStorage.getItem(TAB_SESSION_STORAGE_KEY);
  if (existing) return existing;
  const tabSessionId = createSecureTabId();
  sessionStorage.setItem(TAB_SESSION_STORAGE_KEY, tabSessionId);
  return tabSessionId;
}

export function startNewTabSession() {
  const tabSessionId = createSecureTabId();
  sessionStorage.setItem(TAB_SESSION_STORAGE_KEY, tabSessionId);
  return tabSessionId;
}

export function clearTabSessionId() {
  sessionStorage.removeItem(TAB_SESSION_STORAGE_KEY);
}

export { TAB_SESSION_STORAGE_KEY };
