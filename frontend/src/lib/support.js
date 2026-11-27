export const SUPPORT_CATEGORIES = {
  technical: "Problema técnico",
  usage: "Dúvida de utilização",
  suggestion: "Sugestão de melhoria",
  billing: "Financeiro e assinatura",
  account: "Conta e cadastro",
  other: "Outros",
};

export const SUPPORT_STATUSES = {
  awaiting_support: "Aguardando suporte",
  awaiting_customer: "Aguardando cliente",
  resolved: "Resolvido",
};

const timestamp = new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" });
const updateTime = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

export function formatSupportDate(value) {
  const date = new Date(value);
  return value && !Number.isNaN(date.valueOf()) ? timestamp.format(date) : "—";
}

export function formatSupportUpdatedAt(value, now = new Date()) {
  if (value == null || value === "") return "—";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "—";

  const day = date.toDateString();
  if (day === now.toDateString()) return `Atualizado às ${updateTime.format(date)}`;

  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (day === yesterday.toDateString()) return `Atualizado ontem às ${updateTime.format(date)}`;

  const dateLabel = String(date.getDate()).padStart(2, "0");
  const monthLabel = String(date.getMonth() + 1).padStart(2, "0");
  const yearLabel = String(date.getFullYear()).padStart(4, "0");
  return `Atualizado em ${dateLabel}/${monthLabel}/${yearLabel}`;
}

// Reuse the same identifier if the user retries an identical request after a
// timeout. A new payload or a confirmed success allows a different operation.
export function supportRequestId(attempt, payload) {
  const serialized = JSON.stringify(payload);
  if (attempt.current?.payload !== serialized) {
    attempt.current = { payload: serialized, id: window.crypto.randomUUID() };
  }
  return attempt.current.id;
}
