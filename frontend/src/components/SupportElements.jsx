import { AlertCircle } from "lucide-react";
import { SUPPORT_STATUSES } from "@/lib/support";

const statusColor = {
  awaiting_support: "dh-chip-warning",
  awaiting_customer: "dh-chip-neutral",
  resolved: "dh-chip-success",
};

export function TicketStatus({ status, testId }) {
  return <span className={`dh-chip dh-chip-dot shrink-0 ${statusColor[status] || "dh-chip-neutral"}`} data-testid={testId}>{SUPPORT_STATUSES[status]}</span>;
}

export function TicketUnread() {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-[var(--dh-muted-strong)]" data-testid="support-ticket-unread">
      <span className="h-2 w-2 shrink-0 rounded-full bg-[var(--dh-accent)]" aria-hidden /> Novidades
    </span>
  );
}

export function SupportError({ error, retry }) {
  if (!error) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border border-[var(--dh-error-bd)] bg-[var(--dh-error-bg)] p-3 text-sm text-[var(--dh-error-fg)]" role="alert" data-testid="support-error">
      <AlertCircle size={16} aria-hidden />
      <span className="min-w-0 flex-1 break-words">{error}</span>
      {retry && <button type="button" onClick={retry} className="dh-btn dh-btn-outline">Tentar novamente</button>}
    </div>
  );
}

export function SupportLoading() {
  return (
    <div className="dh-card grid gap-3 p-5" role="status" aria-label="Carregando">
      <div className="dh-skeleton h-4 w-40 max-w-full" /><div className="dh-skeleton h-4 w-full" /><div className="dh-skeleton h-4 w-2/3" />
    </div>
  );
}
