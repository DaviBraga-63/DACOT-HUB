import { useCallback, useEffect, useRef, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { CheckCircle2, ChevronLeft, ChevronRight, Headset, MessageCircle, Plus, Search } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { canUseSupport, useSupportNotifications, useSupportPolling } from "@/context/SupportNotifications";
import { api, formatApiErrorDetail } from "@/lib/api";
import { formatSupportDate, supportRequestId, SUPPORT_CATEGORIES, SUPPORT_STATUSES } from "@/lib/support";
import { SupportError, SupportLoading, TicketStatus, TicketUnread } from "@/components/SupportElements";
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import SupportConversation from "@/pages/SupportConversation";

const initialFilters = { q: "", status: "all", category: "", unread: false, page: 1 };
const staffCounts = [
  ["awaiting_support", "Aguardando suporte", Headset, "dh-chip-warning"],
  ["awaiting_customer", "Aguardando cliente", MessageCircle, "dh-support-info"],
  ["resolved", "Resolvidos", CheckCircle2, "dh-chip-success"],
];
const ownerStatuses = [
  ["all", "Todos"],
  ["open", "Em aberto"],
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
        <button type="button" className="dh-btn dh-btn-primary min-h-11 self-start sm:min-h-12" data-testid="support-new-ticket"><Plus size={20} aria-hidden /> Novo ticket</button>
      </DialogTrigger>
      <DialogContent className="max-h-[90dvh] max-w-[min(42rem,calc(100vw-2rem))] gap-6 overflow-y-auto border-[var(--dh-border)] bg-[var(--dh-surface)] p-5 text-[var(--dh-text)] sm:p-8">
        <div className="space-y-2 pr-6">
          <DialogTitle className="dh-font-display text-2xl sm:text-3xl">Novo ticket</DialogTitle>
          <DialogDescription className="text-[15px] leading-relaxed text-[var(--dh-muted)]">Informe o assunto e explique em que podemos ajudar.</DialogDescription>
        </div>
        <form className="grid gap-5" onSubmit={submit}>
          <label className="grid gap-2 text-sm font-semibold">
            Categoria
            <select name="category" className="dh-input min-h-11" value={draft.category} onChange={edit} disabled={busy} required data-testid="support-category">
              <option value="">Selecione uma categoria</option>
              {Object.entries(SUPPORT_CATEGORIES).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
            </select>
          </label>
          <label className="grid gap-2 text-sm font-semibold">
            Assunto
            <input name="subject" className="dh-input min-h-11" value={draft.subject} onChange={edit} maxLength={120} placeholder="Resuma o motivo do contato" disabled={busy} required data-testid="support-subject" />
          </label>
          <label className="grid gap-2 text-sm font-semibold">
            Descrição
            <textarea name="message" className="dh-input min-h-40 resize-y leading-relaxed sm:min-h-48" value={draft.message} onChange={edit} maxLength={4000} placeholder="Descreva detalhadamente a situação para que possamos ajudar." disabled={busy} required data-testid="support-description" />
          </label>
          <SupportError error={error} />
          <div className="flex flex-wrap justify-end gap-3 border-t border-[var(--dh-border-soft)] pt-4">
            <button className="dh-btn dh-btn-ghost min-h-11" disabled={busy} type="button" onClick={() => setOpen(false)}>Cancelar</button>
            <button className="dh-btn dh-btn-primary min-h-11" disabled={busy} type="submit" data-testid="support-create">{busy ? "Abrindo…" : "Abrir ticket"}</button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function TicketRow({ ticket, staff, basePath }) {
  const priority = staff && ticket.status === "awaiting_support";
  return (
    <li className="min-w-0">
      <Link to={`${basePath}/${ticket.id}`} className="dh-card group relative grid min-w-0 gap-4 p-5 transition-colors hover:bg-[var(--dh-surface-hover)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--dh-accent)] sm:p-6" data-testid={`support-ticket-${ticket.id}`}>
        {(ticket.unread || priority) && <span className={`pointer-events-none absolute inset-y-0 left-0 w-0.5 ${ticket.unread ? "bg-[var(--dh-accent)]" : "bg-[var(--dh-warning-bd)]"}`} aria-hidden />}
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-[1_1_16rem]">
            <h2 className={`dh-font-display break-words font-bold text-[var(--dh-text)] ${staff ? "text-xl sm:text-2xl" : "text-2xl"}`}>{staff ? ticket.restaurant_name : ticket.subject}</h2>
            <span className="mt-1 block break-all font-mono text-xs text-[var(--dh-muted)]">{ticket.number}</span>
          </div>
          <div className="flex max-w-full flex-wrap items-center gap-2 sm:gap-3">
            {ticket.unread && <TicketUnread />}
            <TicketStatus status={ticket.status} />
            <ChevronRight size={19} className="shrink-0 text-[var(--dh-muted)] transition-colors group-hover:text-[var(--dh-accent)] group-focus-visible:text-[var(--dh-accent)]" aria-hidden />
          </div>
        </div>
        <div className={`grid min-w-0 gap-3 ${staff ? "md:grid-cols-[minmax(0,3fr)_minmax(0,1fr)_minmax(0,1fr)]" : "md:grid-cols-[minmax(0,4fr)_minmax(0,1fr)]"}`}>
          <div className="min-w-0">
            {staff && <h3 className="break-words text-lg font-semibold leading-snug text-[var(--dh-text)]">{ticket.subject}</h3>}
            {ticket.last_message_preview && <p className={`line-clamp-2 break-words text-sm leading-relaxed text-[var(--dh-muted-strong)] ${staff ? "mt-1" : ""}`}>{ticket.last_message_preview}</p>}
          </div>
          {staff && <div className="grid min-w-0 content-start gap-1">
            <span className="text-xs text-[var(--dh-muted)]">Solicitante</span>
            <span className="break-words text-sm font-semibold text-[var(--dh-text)]">{ticket.requester_name}</span>
          </div>}
          <div className="grid min-w-0 content-start gap-1">
            <span className="text-xs text-[var(--dh-muted)]">Categoria</span>
            <span className="break-words text-sm font-semibold text-[var(--dh-text)]">{SUPPORT_CATEGORIES[ticket.category]}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-x-7 gap-y-1.5 border-t border-[var(--dh-border-soft)] pt-3 text-xs leading-relaxed text-[var(--dh-muted)] sm:text-sm">
          <span>Aberto em <time className="font-medium text-[var(--dh-muted-strong)]" dateTime={ticket.created_at}>{formatSupportDate(ticket.created_at)}</time></span>
          <span>Última atividade <time className="font-medium text-[var(--dh-muted-strong)]" dateTime={ticket.updated_at}>{formatSupportDate(ticket.updated_at)}</time></span>
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
    <div className="dh-fade-in w-full min-w-0 space-y-7 sm:space-y-8" data-testid="support-center-page">
      <header className="flex flex-wrap items-start justify-between gap-4 sm:items-center sm:gap-5">
        <div className="min-w-0">
          <h1 className="mb-2 dh-font-display text-3xl font-bold tracking-tight text-[var(--dh-text)] sm:text-4xl">Central de Suporte</h1>
          <p className="text-[15px] leading-relaxed text-[var(--dh-muted)]">{staff ? "Acompanhe e responda aos chamados dos restaurantes." : "Acompanhe suas solicitações e fale diretamente com nossa equipe."}</p>
        </div>
        {!staff && <NewTicket apiPath={apiPath} basePath={basePath} />}
      </header>

      {staff && (
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-3 lg:gap-5" aria-label="Resumo dos atendimentos">
          {staffCounts.map(([status, label, Icon, tone]) => (
            <button key={status} type="button" className={`dh-card grid min-h-32 min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-3 p-5 text-left transition-colors hover:bg-[var(--dh-surface-hover)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--dh-accent)] lg:min-h-36 lg:p-6 ${filters.status === status ? "outline outline-1 outline-[var(--dh-accent)]" : ""}`}
              aria-pressed={filters.status === status} onClick={() => changeFilter("status", filters.status === status ? "all" : status)} data-testid={`support-overview-${status}`}>
              <div className="grid min-w-0 gap-2">
                <span className="text-sm font-semibold text-[var(--dh-muted-strong)]">{label}</span>
                {counts?.[status] == null ? <span className="dh-skeleton h-10 w-14 max-w-full" /> : <strong className="dh-kpi-value tabular-nums">{counts[status]}</strong>}
              </div>
              <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border lg:h-12 lg:w-12 ${tone}`}>
                <Icon size={23} strokeWidth={1.75} aria-hidden />
              </span>
            </button>
          ))}
        </section>
      )}

      <div className={`dh-card grid min-w-0 items-end gap-4 p-5 lg:p-6 ${staff ? "sm:grid-cols-2 xl:grid-cols-[minmax(0,1fr)_minmax(9rem,0.25fr)_minmax(10rem,0.25fr)_auto]" : "lg:grid-cols-[auto_minmax(0,1fr)]"}`}>
        {!staff && (
          <div className="grid min-w-0 grid-cols-3 items-stretch gap-1 rounded-lg border border-[var(--dh-border)] bg-[var(--dh-surface-secondary)] p-1 lg:min-w-[19rem]" role="group" aria-label="Filtrar tickets por status" data-testid="support-status-filter">
            {ownerStatuses.map(([key, label]) => (
              <button key={key} type="button" className={`dh-filter-pill min-h-9 min-w-0 !rounded-md !px-2 leading-tight ${filters.status === key ? "dh-filter-pill-active" : ""}`} aria-pressed={filters.status === key}
                onClick={() => changeFilter("status", key)} data-testid={`support-status-${key}`}>{label}</button>
            ))}
          </div>
        )}
        <label className={`grid min-w-0 gap-2 text-sm font-semibold text-[var(--dh-text)] ${staff ? "sm:col-span-2 xl:col-span-1" : ""}`}>
          Pesquisar
          <span className="relative">
            <Search size={18} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--dh-muted)]" aria-hidden />
            <input type="search" className="dh-input min-h-11 !pl-10" value={search} onChange={(event) => setSearch(event.target.value)} maxLength={120}
              placeholder={staff ? "Restaurante, assunto ou número" : "Assunto ou número do ticket"} data-testid="support-search" />
          </span>
        </label>
        {staff && (
          <>
            <label className="grid min-w-0 gap-2 text-sm font-semibold text-[var(--dh-text)]">
              Status
              <select className="dh-input min-h-11" value={filters.status} onChange={(event) => changeFilter("status", event.target.value)} data-testid="support-status-filter">
                <option value="all">Todos</option>
                {Object.entries(SUPPORT_STATUSES).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
              </select>
            </label>
            <label className="grid min-w-0 gap-2 text-sm font-semibold text-[var(--dh-text)]">
              Categoria
              <select className="dh-input min-h-11" value={filters.category} onChange={(event) => changeFilter("category", event.target.value)} data-testid="support-category-filter">
                <option value="">Todas</option>
                {Object.entries(SUPPORT_CATEGORIES).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
              </select>
            </label>
            <label className="flex min-h-11 min-w-0 items-center gap-2 text-sm font-medium text-[var(--dh-text)] sm:col-span-2 xl:col-span-1 xl:pl-1">
              <input type="checkbox" className="h-4 w-4 accent-[var(--dh-accent)]" checked={filters.unread} onChange={(event) => changeFilter("unread", event.target.checked)} data-testid="support-unread-filter" />
              Só não lidos
            </label>
          </>
        )}
      </div>

      <SupportError error={error} retry={reload} />
      {!data && !error && <SupportLoading />}
      {data?.items.length === 0 && (
        <div className="dh-card flex flex-col items-center gap-3 px-6 py-14 text-center">
          <span className="dh-icon-tile rounded-lg p-3"><Headset size={23} aria-hidden /></span>
          <h2 className="font-semibold text-[var(--dh-text)]">{hasFilters ? "Nenhum ticket encontrado" : "Nenhum ticket ainda"}</h2>
          <p className="text-sm text-[var(--dh-muted)]">{hasFilters ? "Tente outra busca ou altere os filtros." : staff ? "Os chamados dos restaurantes aparecerão aqui." : "Abra um ticket quando precisar falar com nossa equipe."}</p>
        </div>
      )}
      {data?.items.length > 0 && (
        <section className="space-y-4" aria-label="Tickets">
          <ul className="grid gap-4">{data.items.map((ticket) => <TicketRow key={ticket.id} ticket={ticket} staff={staff} basePath={basePath} />)}</ul>
          {pages > 1 && (
            <nav className="dh-card flex flex-wrap items-center justify-between gap-3 p-4 sm:px-6" aria-label="Paginação dos tickets">
              <button type="button" className="dh-btn dh-btn-outline min-h-10 disabled:opacity-50" onClick={() => changePage(-1)} disabled={data.page <= 1} data-testid="support-prev-page"><ChevronLeft size={16} aria-hidden /> Anterior</button>
              <span className="text-sm text-[var(--dh-muted)]">Página {data.page} de {pages}</span>
              <button type="button" className="dh-btn dh-btn-outline min-h-10 disabled:opacity-50" onClick={() => changePage(1)} disabled={data.page >= pages} data-testid="support-next-page">Próxima <ChevronRight size={16} aria-hidden /></button>
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
