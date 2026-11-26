import { useCallback, useEffect, useRef, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { ChevronLeft, ChevronRight, Headset, Plus, Search } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { canUseSupport, useSupportNotifications, useSupportPolling } from "@/context/SupportNotifications";
import { api, formatApiErrorDetail } from "@/lib/api";
import { formatSupportDate, supportRequestId, SUPPORT_CATEGORIES, SUPPORT_STATUSES } from "@/lib/support";
import { SupportError, SupportLoading, TicketStatus, TicketUnread } from "@/components/SupportElements";
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import SupportConversation from "@/pages/SupportConversation";

const initialFilters = { q: "", status: "all", category: "", unread: false, page: 1 };
const staffCounts = [
  ["awaiting_support", "Aguardando suporte"],
  ["awaiting_customer", "Aguardando cliente"],
  ["resolved", "Resolvidos"],
];

function NewTicket({ apiPath, basePath }) {
  const navigate = useNavigate();
  const { refresh } = useSupportNotifications();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState({ category: "", subject: "", message: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const attempt = useRef(null);
  const sending = useRef(false);

  const edit = ({ target: { name, value } }) => setDraft((current) => ({ ...current, [name]: value }));
  const submit = async (event) => {
    event.preventDefault();
    if (sending.current) return;
    const payload = { category: draft.category, subject: draft.subject.trim(), message: draft.message.trim() };
    if (!SUPPORT_CATEGORIES[payload.category] || !payload.subject || !payload.message) {
      setError("Preencha a categoria, o assunto e a descrição.");
      return;
    }
    if (payload.subject.length > 120 || payload.message.length > 4000) {
      setError("Use até 120 caracteres no assunto e 4.000 na descrição.");
      return;
    }
    sending.current = true;
    setBusy(true);
    setError(null);
    try {
      const { data } = await api.post(`${apiPath}/tickets`, {
        ...payload, request_id: supportRequestId(attempt, payload),
      });
      attempt.current = null;
      void refresh();
      navigate(`${basePath}/${data.id}`);
    } catch (failure) {
      setError(formatApiErrorDetail(failure.response?.data?.detail));
    } finally {
      sending.current = false;
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!sending.current) setOpen(next); }}>
      <DialogTrigger asChild>
        <button type="button" className="dh-btn dh-btn-primary self-start" data-testid="support-new-ticket"><Plus size={17} aria-hidden /> Novo ticket</button>
      </DialogTrigger>
      <DialogContent className="max-h-[90dvh] max-w-[min(32rem,calc(100vw-2rem))] overflow-y-auto border-[var(--dh-border)] bg-[var(--dh-surface)] text-[var(--dh-text)]">
        <DialogTitle className="dh-font-display text-xl">Novo ticket</DialogTitle>
        <DialogDescription className="text-[var(--dh-muted)]">Informe o assunto e explique em que podemos ajudar.</DialogDescription>
        <form className="grid gap-4" onSubmit={submit}>
          <label className="grid gap-1.5 text-sm font-medium">
            Categoria
            <select name="category" className="dh-input w-full" value={draft.category} onChange={edit} disabled={busy} required data-testid="support-category">
              <option value="">Selecione uma categoria</option>
              {Object.entries(SUPPORT_CATEGORIES).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
            </select>
          </label>
          <label className="grid gap-1.5 text-sm font-medium">
            Assunto
            <input name="subject" className="dh-input w-full" value={draft.subject} onChange={edit} maxLength={120} placeholder="Resuma o motivo do contato" disabled={busy} required data-testid="support-subject" />
          </label>
          <label className="grid gap-1.5 text-sm font-medium">
            Descrição
            <textarea name="message" className="dh-input min-h-32 w-full resize-y" value={draft.message} onChange={edit} maxLength={4000} placeholder="Descreva detalhadamente a situação para que possamos ajudar." disabled={busy} required data-testid="support-description" />
          </label>
          <SupportError error={error} />
          <div className="flex flex-wrap justify-end gap-2">
            <button className="dh-btn dh-btn-ghost" disabled={busy} type="button" onClick={() => setOpen(false)}>Cancelar</button>
            <button className="dh-btn dh-btn-primary" disabled={busy} type="submit" data-testid="support-create">{busy ? "Abrindo…" : "Abrir ticket"}</button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function TicketRow({ ticket, staff, basePath }) {
  const priority = staff && ticket.status === "awaiting_support";
  return (
    <li className={`border-b border-[var(--dh-border-soft)] last:border-b-0 ${priority || ticket.unread ? "bg-[var(--dh-accent-soft)]" : ""}`}>
      <Link to={`${basePath}/${ticket.id}`} className="grid min-w-0 gap-2.5 px-4 py-4 hover:bg-[var(--dh-surface-hover)] focus-visible:outline-2 focus-visible:outline-[var(--dh-accent)] sm:px-5" data-testid={`support-ticket-${ticket.id}`}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="font-mono text-xs font-semibold text-[var(--dh-muted-strong)]">{ticket.number}</span>
          <div className="flex flex-wrap items-center gap-2">
            {ticket.unread && <TicketUnread />}
            <TicketStatus status={ticket.status} />
          </div>
        </div>
        <div className="min-w-0">
          <h2 className={`break-words text-base text-[var(--dh-text)] ${ticket.unread ? "font-bold" : "font-semibold"}`}>{ticket.subject}</h2>
          {staff && <p className="mt-1 break-words text-sm text-[var(--dh-muted-strong)]">{ticket.restaurant_name} · {ticket.requester_name}</p>}
          {ticket.last_message_preview && <p className="mt-1 truncate text-sm text-[var(--dh-muted)]">{ticket.last_message_preview}</p>}
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--dh-muted)]">
          <span>{SUPPORT_CATEGORIES[ticket.category]}</span>
          <span>Aberto em <time dateTime={ticket.created_at}>{formatSupportDate(ticket.created_at)}</time></span>
          <span>Atualizado em <time dateTime={ticket.updated_at}>{formatSupportDate(ticket.updated_at)}</time></span>
        </div>
      </Link>
    </li>
  );
}

function TicketList({ staff, apiPath, basePath }) {
  const [filters, setFilters] = useState(initialFilters);
  const [search, setSearch] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const request = useRef(null);

  const changeFilter = (field, value) => setFilters((active) => ({ ...active, [field]: value, page: 1 }));
  const changePage = (delta) => setFilters((active) => ({ ...active, page: active.page + delta }));
  useEffect(() => {
    const timeout = window.setTimeout(() => {
      const value = search.trim();
      setFilters((active) => active.q === value ? active : { ...active, q: value, page: 1 });
    }, 250);
    return () => window.clearTimeout(timeout);
  }, [search]);

  const reload = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    try {
      const params = { ...filters, category: filters.category || undefined };
      const { data } = await api.get(`${apiPath}/tickets`, { params, signal: controller.signal });
      if (controller.signal.aborted) return;
      const lastPage = Math.max(1, Math.ceil(data.total / data.page_size));
      if (filters.page > lastPage) {
        setFilters((active) => ({ ...active, page: lastPage }));
        return;
      }
      setResult({ filters, data });
      setError(null);
    } catch (failure) {
      if (!controller.signal.aborted) setError(formatApiErrorDetail(failure.response?.data?.detail));
    }
  }, [apiPath, filters]);

  useEffect(() => {
    setError(null);
    void reload();
    return () => request.current?.abort();
  }, [reload]);
  useSupportPolling(reload);

  const data = result?.filters === filters ? result.data : null;
  const counts = result?.data.counts;
  const hasFilters = Boolean(filters.q || filters.status !== "all" || filters.category || filters.unread);
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <div className="mx-auto max-w-6xl space-y-5 dh-fade-in" data-testid="support-center-page">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="dh-font-display text-3xl font-bold tracking-tight text-[var(--dh-text)]">Central de Suporte</h1>
          <p className="mt-2 text-sm text-[var(--dh-muted)]">{staff ? "Acompanhe e responda aos chamados dos restaurantes." : "Acompanhe suas solicitações e fale diretamente com nossa equipe."}</p>
        </div>
        {!staff && <NewTicket apiPath={apiPath} basePath={basePath} />}
      </header>

      {staff && (
        <section className="grid grid-cols-1 gap-3 sm:grid-cols-3" aria-label="Resumo dos atendimentos">
          {staffCounts.map(([status, label]) => (
            <button key={status} type="button" className={`dh-card flex items-center justify-between gap-3 px-4 py-3 text-left hover:bg-[var(--dh-surface-hover)] ${filters.status === status ? "outline outline-2 outline-[var(--dh-accent)]" : ""}`}
              aria-pressed={filters.status === status} onClick={() => changeFilter("status", filters.status === status ? "all" : status)}>
              <span className="text-sm font-medium text-[var(--dh-muted-strong)]">{label}</span>
              <strong className="dh-font-display text-xl text-[var(--dh-text)]">{counts?.[status] ?? "—"}</strong>
            </button>
          ))}
        </section>
      )}

      <div className={`dh-card grid items-end gap-3 p-4 ${staff ? "lg:grid-cols-[minmax(0,1fr)_180px_200px_auto]" : "sm:grid-cols-[minmax(0,1fr)_200px]"}`}>
        <label className="grid min-w-0 gap-1.5 text-sm font-medium text-[var(--dh-text)]">
          Pesquisar
          <span className="relative">
            <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--dh-muted)]" aria-hidden />
            <input type="search" className="dh-input w-full !pl-9" value={search} onChange={(event) => setSearch(event.target.value)} maxLength={120}
              placeholder={staff ? "Restaurante, assunto ou número" : "Assunto ou número do ticket"} data-testid="support-search" />
          </span>
        </label>
        <label className="grid min-w-0 gap-1.5 text-sm font-medium text-[var(--dh-text)]">
          Status
          <select className="dh-input w-full" value={filters.status} onChange={(event) => changeFilter("status", event.target.value)} data-testid="support-status-filter">
            <option value="all">Todos</option>
            {staff ? Object.entries(SUPPORT_STATUSES).map(([key, label]) => <option key={key} value={key}>{label}</option>) : (
              <><option value="open">Em aberto</option><option value="resolved">Resolvidos</option></>
            )}
          </select>
        </label>
        {staff && (
          <>
            <label className="grid min-w-0 gap-1.5 text-sm font-medium text-[var(--dh-text)]">
              Categoria
              <select className="dh-input w-full" value={filters.category} onChange={(event) => changeFilter("category", event.target.value)} data-testid="support-category-filter">
                <option value="">Todas</option>
                {Object.entries(SUPPORT_CATEGORIES).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
              </select>
            </label>
            <label className="flex min-h-10 items-center gap-2 text-sm font-medium text-[var(--dh-text)]">
              <input type="checkbox" className="h-4 w-4 accent-[var(--dh-accent)]" checked={filters.unread} onChange={(event) => changeFilter("unread", event.target.checked)} data-testid="support-unread-filter" />
              Só não lidos
            </label>
          </>
        )}
      </div>

      <SupportError error={error} retry={reload} />
      {!data && !error && <SupportLoading />}
      {data?.items.length === 0 && (
        <div className="dh-card flex flex-col items-center gap-3 p-8 text-center">
          <span className="dh-icon-tile rounded-lg p-3"><Headset size={23} aria-hidden /></span>
          <h2 className="font-semibold text-[var(--dh-text)]">{hasFilters ? "Nenhum ticket encontrado" : "Nenhum ticket ainda"}</h2>
          <p className="text-sm text-[var(--dh-muted)]">{hasFilters ? "Tente outra busca ou altere os filtros." : staff ? "Os chamados dos restaurantes aparecerão aqui." : "Abra um ticket quando precisar falar com nossa equipe."}</p>
        </div>
      )}
      {data?.items.length > 0 && (
        <section className="dh-card" aria-label="Tickets">
          <ul>{data.items.map((ticket) => <TicketRow key={ticket.id} ticket={ticket} staff={staff} basePath={basePath} />)}</ul>
          {pages > 1 && (
            <nav className="flex flex-wrap items-center justify-between gap-2 border-t border-[var(--dh-border-soft)] p-3" aria-label="Paginação dos tickets">
              <button type="button" className="dh-btn dh-btn-outline disabled:opacity-50" onClick={() => changePage(-1)} disabled={data.page <= 1} data-testid="support-prev-page"><ChevronLeft size={16} aria-hidden /> Anterior</button>
              <span className="text-sm text-[var(--dh-muted)]">Página {data.page} de {pages}</span>
              <button type="button" className="dh-btn dh-btn-outline disabled:opacity-50" onClick={() => changePage(1)} disabled={data.page >= pages} data-testid="support-next-page">Próxima <ChevronRight size={16} aria-hidden /></button>
            </nav>
          )}
        </section>
      )}
    </div>
  );
}

export function SupportCenter({ staff = false }) {
  const { user } = useAuth();
  if (!canUseSupport(user, staff)) return <Navigate to={staff ? "/painel" : "/portal"} replace />;
  return <TicketList staff={staff} apiPath={staff ? "/hub/support" : "/portal/support"} basePath={staff ? "/suporte" : "/portal/suporte"} />;
}

export function SupportTicket({ staff = false }) {
  const { user } = useAuth();
  const { ticketId } = useParams();
  if (!canUseSupport(user, staff)) return <Navigate to={staff ? "/painel" : "/portal"} replace />;
  return <SupportConversation key={ticketId} staff={staff} ticketId={ticketId} apiPath={staff ? "/hub/support" : "/portal/support"} basePath={staff ? "/suporte" : "/portal/suporte"} />;
}
