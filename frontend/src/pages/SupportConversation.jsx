import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, ArrowUpRight, Check, RotateCcw, Send } from "lucide-react";
import { useSupportNotifications, useSupportPolling } from "@/context/SupportNotifications";
import { api, formatApiErrorDetail } from "@/lib/api";
import { formatSupportDate, supportRequestId, SUPPORT_CATEGORIES } from "@/lib/support";
import { SupportError, SupportLoading, TicketStatus } from "@/components/SupportElements";
import StatusBadge from "@/components/StatusBadge";
import {
  AlertDialog, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogTitle,
} from "@/components/ui/alert-dialog";

function mergeMessages(earlier, later) {
  return Array.from(new Map([...earlier, ...later].map((message) => [message.seq, message])).values())
    .sort((left, right) => left.seq - right.seq);
}

function ConversationMessage({ message, staff }) {
  const fromRestaurant = message.author_type === "restaurant";
  const author = !staff && !fromRestaurant ? "Equipe DACOT"
    : message.is_mine ? "Você" : message.author_label;
  const time = <time dateTime={message.created_at}>{formatSupportDate(message.created_at)}</time>;

  if (message.kind !== "message") {
    const label = message.kind === "resolved" ? "Ticket marcado como resolvido" : "Ticket reaberto";
    return <li className="my-1 text-center text-xs text-[var(--dh-muted)]">{label} · {time}</li>;
  }

  return (
    <li className={`flex ${fromRestaurant ? "justify-end" : "justify-start"}`} data-testid="support-message">
      <div className={`min-w-0 max-w-[90%] rounded-lg border border-[var(--dh-border-soft)] px-3 py-2.5 sm:max-w-[80%] sm:px-4 ${fromRestaurant ? "bg-[var(--dh-accent-soft)]" : "bg-[var(--dh-surface-secondary)]"}`}>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--dh-muted)]">
          <span className="font-semibold text-[var(--dh-text)]">{author}</span>
          {time}
        </div>
        <p className="mt-1 whitespace-pre-wrap break-words text-sm leading-relaxed text-[var(--dh-text)] [overflow-wrap:anywhere]">{message.text}</p>
      </div>
    </li>
  );
}

function ClientDetails({ restaurant, ticket }) {
  const fields = [
    ["Restaurante", restaurant.name],
    ["Identificador", restaurant.id],
    ["Responsável", restaurant.owner_name],
    ["Solicitante", restaurant.requester_name],
    ["E-mail", restaurant.email],
    ["WhatsApp", restaurant.whatsapp],
    ["Status da conta", restaurant.status ? <StatusBadge status={restaurant.status} /> : null],
    ["Ticket", ticket.number],
    ["Categoria", SUPPORT_CATEGORIES[ticket.category]],
    ["Assunto", ticket.subject],
    ["Abertura", formatSupportDate(ticket.created_at)],
    ["Última atividade", formatSupportDate(ticket.updated_at)],
    ["Atendimento", <TicketStatus status={ticket.status} />],
  ];
  return (
    <aside className="dh-card self-start space-y-4 p-4 sm:p-5" aria-label="Dados do restaurante" data-testid="support-client-details">
      <h2 className="dh-font-display text-lg font-bold text-[var(--dh-text)]">Dados do restaurante</h2>
      <dl className="grid gap-3 text-sm">
        {fields.map(([label, value]) => (
          <div key={label}><dt className="text-xs text-[var(--dh-muted)]">{label}</dt><dd className="mt-0.5 min-w-0 break-words font-medium text-[var(--dh-text)] [overflow-wrap:anywhere]">{value || "—"}</dd></div>
        ))}
      </dl>
      {restaurant.id && <Link to={`/clientes/${restaurant.id}`} className="dh-btn dh-btn-outline w-full justify-center">Abrir cadastro <ArrowUpRight size={15} aria-hidden /></Link>}
    </aside>
  );
}

export default function SupportConversation({ staff, ticketId, apiPath, basePath }) {
  const path = `${apiPath}/tickets/${encodeURIComponent(ticketId)}`;
  const { refresh } = useSupportNotifications();
  const [thread, setThread] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [historyError, setHistoryError] = useState(null);
  const [olderBusy, setOlderBusy] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(null);
  const [mutationError, setMutationError] = useState(null);
  const [resolving, setResolving] = useState(false);
  const [pinned, setPinned] = useState(true);
  const [visible, setVisible] = useState(() => document.visibilityState !== "hidden");
  const currentRequest = useRef(null);
  const olderRequest = useRef(null);
  const scroller = useRef(null);
  const olderScroll = useRef(null);
  const submitting = useRef(false);
  const messageAttempt = useRef(null);
  const statusAttempt = useRef(null);
  const readThrough = useRef(0);

  const load = useCallback(async () => {
    currentRequest.current?.abort();
    const controller = new AbortController();
    currentRequest.current = controller;
    try {
      const { data } = await api.get(path, { signal: controller.signal });
      if (controller.signal.aborted) return;
      setThread((current) => {
        if (!current?.messages.length || !data.messages.length || data.messages[0].seq > current.messages.at(-1).seq + 1) return data;
        return { ...data, messages: mergeMessages(current.messages, data.messages), next_before: current.next_before };
      });
      setLoadError(null);
    } catch (failure) {
      if (controller.signal.aborted) return;
      if ([401, 403, 404].includes(failure.response?.status)) setThread(null);
      setLoadError(formatApiErrorDetail(failure.response?.data?.detail));
    }
  }, [path]);

  useEffect(() => {
    void load();
    return () => {
      currentRequest.current?.abort();
      olderRequest.current?.abort();
    };
  }, [load]);
  useSupportPolling(load, 15_000);

  useEffect(() => {
    const onVisibility = () => setVisible(document.visibilityState !== "hidden");
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  useLayoutEffect(() => {
    const element = scroller.current;
    if (!element) return;
    if (olderScroll.current) {
      const { height, top } = olderScroll.current;
      olderScroll.current = null;
      element.scrollTop = top + element.scrollHeight - height;
    } else if (pinned) {
      element.scrollTop = element.scrollHeight;
    }
  }, [thread?.messages, pinned]);

  useEffect(() => {
    const through = thread?.through;
    if (!visible || !pinned || !through || through <= readThrough.current) return undefined;
    const controller = new AbortController();
    api.post(`${path}/read`, { through }, { signal: controller.signal })
      .then(() => {
        if (controller.signal.aborted) return;
        readThrough.current = Math.max(readThrough.current, through);
        void refresh();
      })
      .catch(() => { /* A later visible conversation refresh can retry. */ });
    return () => controller.abort();
  }, [path, pinned, refresh, thread, visible]);

  const loadOlder = async () => {
    const before = thread.next_before;
    if (olderRequest.current || !before) return;
    const controller = new AbortController();
    olderRequest.current = controller;
    setOlderBusy(true);
    setHistoryError(null);
    try {
      const { data } = await api.get(path, { params: { before }, signal: controller.signal });
      if (controller.signal.aborted) return;
      if (scroller.current) {
        olderScroll.current = { height: scroller.current.scrollHeight, top: scroller.current.scrollTop };
      }
      setThread((current) => current && current.next_before === before
        ? { ...current, messages: mergeMessages(data.messages, current.messages), next_before: data.next_before }
        : current);
    } catch (failure) {
      if (!controller.signal.aborted) setHistoryError(formatApiErrorDetail(failure.response?.data?.detail));
    } finally {
      olderRequest.current = null;
      if (!controller.signal.aborted) setOlderBusy(false);
    }
  };

  const mutate = async (action, payload, attempt, onSuccess) => {
    if (submitting.current) return;
    submitting.current = true;
    setBusy(action);
    setMutationError(null);
    try {
      await api.post(`${path}/${action}`, { ...payload, request_id: supportRequestId(attempt, payload) });
      attempt.current = null;
      onSuccess();
      await load();
      void refresh();
    } catch (failure) {
      setMutationError(formatApiErrorDetail(failure.response?.data?.detail));
      if (failure.response?.status === 409) void load();
    } finally {
      submitting.current = false;
      setBusy(null);
    }
  };

  const send = (event) => {
    event.preventDefault();
    const message = text.trim();
    if (!message) {
      setMutationError("Escreva uma mensagem antes de enviar.");
      return;
    }
    if (message.length > 4000) {
      setMutationError("Use até 4.000 caracteres na mensagem.");
      return;
    }
    void mutate("messages", { message }, messageAttempt, () => {
      setText("");
      setPinned(true);
    });
  };
  const changeStatus = (status) => mutate("status", { status }, statusAttempt, () => setResolving(false));

  return (
    <div className="mx-auto max-w-6xl space-y-4 dh-fade-in" data-testid="support-conversation-page">
      <Link to={basePath} className="dh-btn dh-btn-ghost self-start"><ArrowLeft size={16} aria-hidden /> Voltar aos tickets</Link>
      <SupportError error={loadError} retry={load} />
      {!thread && !loadError && <SupportLoading />}
      {thread && (
        <>
          <header className="grid gap-3 sm:flex sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs font-semibold text-[var(--dh-muted-strong)]">{thread.ticket.number}</span>
                <TicketStatus status={thread.ticket.status} testId="support-ticket-status" />
              </div>
              <h1 className="dh-font-display mt-2 break-words text-2xl font-bold tracking-tight text-[var(--dh-text)] sm:text-3xl" data-testid="support-ticket-title">{thread.ticket.subject}</h1>
              <p className="mt-1 text-sm text-[var(--dh-muted)]">{SUPPORT_CATEGORIES[thread.ticket.category]} · Aberto em <time dateTime={thread.ticket.created_at}>{formatSupportDate(thread.ticket.created_at)}</time></p>
            </div>
            {thread.ticket.status === "resolved" ? (
              <button type="button" className="dh-btn dh-btn-outline justify-self-start disabled:opacity-50" disabled={!!busy} onClick={() => changeStatus("awaiting_support")} data-testid="support-reopen">
                <RotateCcw size={16} aria-hidden /> Reabrir ticket
              </button>
            ) : staff && (
              <button type="button" className="dh-btn dh-btn-outline justify-self-start disabled:opacity-50" disabled={!!busy} onClick={() => setResolving(true)} data-testid="support-resolve">
                <Check size={17} aria-hidden /> Marcar como resolvido
              </button>
            )}
          </header>

          <div className={`grid min-w-0 gap-4 ${staff ? "lg:grid-cols-[minmax(0,1fr)_280px]" : ""}`}>
            <section className="dh-card min-w-0" aria-label="Conversa">
              <div className="max-h-[55dvh] min-h-[180px] overflow-y-auto overscroll-contain p-4 sm:p-5" ref={scroller}
                onScroll={(event) => {
                  const { scrollHeight, clientHeight, scrollTop } = event.currentTarget;
                  setPinned(scrollHeight - clientHeight - scrollTop < 50);
                }}>
                {thread.next_before && (
                  <div className="mb-4 text-center">
                    <button className="dh-btn dh-btn-outline disabled:opacity-50" type="button" disabled={olderBusy} onClick={loadOlder} data-testid="support-load-older">
                      {olderBusy ? "Carregando…" : "Carregar mensagens anteriores"}
                    </button>
                  </div>
                )}
                <SupportError error={historyError} />
                <ol className="grid gap-3" aria-label="Histórico da conversa" data-testid="support-message-list">
                  {thread.messages.map((message) => <ConversationMessage key={message.id} message={message} staff={staff} />)}
                </ol>
              </div>
              {!pinned && <button type="button" className="dh-btn dh-btn-ghost m-2" onClick={() => setPinned(true)}>Ir para mensagens recentes</button>}
              <div className="grid gap-3 border-t border-[var(--dh-border-soft)] p-4">
                <SupportError error={mutationError} />
                {thread.ticket.status === "resolved" ? (
                  <p className="text-sm text-[var(--dh-muted)]">Reabra o ticket para continuar a conversa.</p>
                ) : (
                  <form className="grid gap-2" onSubmit={send}>
                    <label className="grid gap-1.5 text-sm font-medium text-[var(--dh-text)]">
                      Mensagem
                      <textarea className="dh-input min-h-20 w-full resize-y" value={text} onChange={(event) => setText(event.target.value)}
                        placeholder="Escreva uma mensagem" required maxLength={4000} disabled={!!busy} data-testid="support-reply-input" />
                    </label>
                    <button className="dh-btn dh-btn-primary justify-self-end" type="submit" disabled={!!busy} data-testid="support-send-reply">
                      <Send size={15} aria-hidden /> {busy === "messages" ? "Enviando…" : "Enviar"}
                    </button>
                  </form>
                )}
              </div>
            </section>
            {staff && thread.restaurant && <ClientDetails restaurant={thread.restaurant} ticket={thread.ticket} />}
          </div>

          <AlertDialog open={resolving} onOpenChange={(next) => { if (!submitting.current) setResolving(next); }}>
            <AlertDialogContent className="max-w-[min(32rem,calc(100vw-2rem))] border-[var(--dh-border)] bg-[var(--dh-surface)] text-[var(--dh-text)]">
              <AlertDialogTitle className="dh-font-display text-xl">Marcar ticket como resolvido?</AlertDialogTitle>
              <AlertDialogDescription className="text-[var(--dh-muted)]">O restaurante receberá uma notificação e poderá reabrir o ticket.</AlertDialogDescription>
              <SupportError error={mutationError} />
              <div className="flex flex-wrap justify-end gap-2">
                <AlertDialogCancel asChild><button className="dh-btn dh-btn-outline" type="button" disabled={!!busy}>Cancelar</button></AlertDialogCancel>
                <button type="button" className="dh-btn dh-btn-primary" disabled={!!busy} onClick={() => changeStatus("resolved")} data-testid="support-confirm-resolve">
                  {busy ? "Concluindo…" : "Confirmar resolução"}
                </button>
              </div>
            </AlertDialogContent>
          </AlertDialog>
        </>
      )}
    </div>
  );
}
