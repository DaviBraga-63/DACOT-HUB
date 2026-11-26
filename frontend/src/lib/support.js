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

export function formatSupportDate(value) {
  const date = new Date(value);
  return value && !Number.isNaN(date.valueOf()) ? timestamp.format(date) : "—";
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
