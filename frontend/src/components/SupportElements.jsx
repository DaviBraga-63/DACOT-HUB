import { AlertCircle } from "lucide-react";
import { SUPPORT_STATUSES } from "../lib/support";

const statusColor = {
  awaiting_support: "dh-chip-warning",
  awaiting_customer: "dh-support-info",
  resolved: "dh-chip-success",
};

export function TicketStatus({ status, staff, testId }) {
  const label = !staff && status === "awaiting_customer" ? "Aguardando sua resposta" : SUPPORT_STATUSES[status];
  return <span className={`dh-chip dh-chip-dot shrink-0 whitespace-nowrap ${statusColor[status] || "dh-chip-neutral"}`} data-testid={testId}>{label}</span>;
}

export function ConversationMessage({ message, staff, timeLabel }) {
  const outgoing = message.author_type === (staff ? "staff" : "restaurant");
  const author = !staff && message.author_type !== "restaurant" ? "Equipe DACOT"
    : message.is_mine ? "Você" : message.author_label;
  const time = <time className="tabular-nums" dateTime={message.created_at}>{timeLabel}</time>;

  if (message.kind !== "message") {
    const label = message.kind === "resolved" ? "Ticket marcado como resolvido" : "Ticket reaberto";
    return <li className="py-1 text-center text-xs leading-relaxed text-[var(--dh-muted)]">{label} · {time}</li>;
  }

  return (
    <li className={`flex ${outgoing ? "justify-end" : "justify-start"}`} data-testid="support-message">
      <div className={`min-w-0 max-w-[min(92%,64ch)] rounded-xl border border-[var(--dh-border-soft)] px-4 py-3 sm:max-w-[min(80%,64ch)] sm:px-5 sm:py-4 ${outgoing ? "rounded-br-sm bg-[var(--dh-accent-soft)]" : "rounded-bl-sm bg-[var(--dh-surface-secondary)]"}`}>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xs text-[var(--dh-muted)]">
          <span className="text-[13px] font-semibold text-[var(--dh-text)] [overflow-wrap:anywhere]">{author}</span>
          {time}
        </div>
        <p className="mt-1.5 whitespace-pre-wrap text-[15px] leading-relaxed text-[var(--dh-text)] [overflow-wrap:anywhere]">{message.text}</p>
      </div>
    </li>
  );
}

export function TicketUnread() {
  return (
    <span className="inline-flex shrink-0 items-center gap-2 whitespace-nowrap text-xs font-semibold text-[var(--dh-muted-strong)]" data-testid="support-ticket-unread">
      <span className="h-2 w-2 shrink-0 rounded-full bg-[var(--dh-accent)]" aria-hidden /> Novidades
    </span>
  );
}

export function SupportError({ error, retry }) {
  if (!error) return null;
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-md border border-[var(--dh-error-bd)] bg-[var(--dh-error-bg)] px-4 py-3 text-sm text-[var(--dh-error-fg)]" role="alert" data-testid="support-error">
      <AlertCircle size={16} aria-hidden />
      <span className="min-w-0 flex-1 break-words">{error}</span>
      {retry && <button type="button" onClick={retry} className="dh-btn dh-btn-outline">Tentar novamente</button>}
    </div>
  );
}

export function SupportLoading() {
  return (
    <div className="dh-card grid gap-3 p-5 sm:gap-4 sm:p-7" role="status" aria-label="Carregando">
      <div className="dh-skeleton h-5 w-48 max-w-full" />
      <div className="dh-skeleton h-4 w-full max-w-2xl" />
      <div className="dh-skeleton h-4 w-2/3 max-w-lg" />
    </div>
  );
}
