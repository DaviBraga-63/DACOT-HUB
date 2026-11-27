import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, ArrowUpRight, Check, RotateCcw, Send } from "lucide-react";
import { useSupportNotifications, useSupportPolling } from "@/context/SupportNotifications";
import { api, formatApiErrorDetail } from "@/lib/api";
import { formatSupportDate, supportRequestId, SUPPORT_CATEGORIES } from "@/lib/support";
import { ConversationMessage, SupportError, SupportLoading, TicketStatus } from "@/components/SupportElements";
import StatusBadge from "@/components/StatusBadge";
import {
  AlertDialog, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogTitle,
} from "@/components/ui/alert-dialog";

function mergeMessages(earlier, later) {
  return Array.from(new Map([...earlier, ...later].map((message) => [message.seq, message])).values())
    .sort((left, right) => left.seq - right.seq);
}

const messageDay = new Intl.DateTimeFormat("pt-BR", { dateStyle: "long" });
const messageTime = new Intl.DateTimeFormat("pt-BR", { timeStyle: "short" });

function formatMessageDate(value, formatter) {
  const date = new Date(value);
  return value && !Number.isNaN(date.valueOf()) ? formatter.format(date) : "";
}

function ConversationHistory({ messages, staff }) {
  return (
    <ol className="grid gap-4 sm:gap-5" aria-label="Histórico da conversa" data-testid="support-message-list">
      {messages.map((message, index) => {
        const day = formatMessageDate(message.created_at, messageDay);
        const previousDay = formatMessageDate(messages[index - 1]?.created_at, messageDay);
        return (
          <Fragment key={message.id}>
            {day && day !== previousDay && (
              <li className="flex items-center gap-3 py-1 text-center sm:gap-4">
                <span aria-hidden className="h-px flex-1 bg-[var(--dh-border-soft)]" />
                <time className="text-xs font-semibold text-[var(--dh-muted-strong)]" dateTime={message.created_at}>{day}</time>
                <span aria-hidden className="h-px flex-1 bg-[var(--dh-border-soft)]" />
              </li>
            )}
            <ConversationMessage message={message} staff={staff} timeLabel={formatMessageDate(message.created_at, messageTime) || "—"} />
          </Fragment>
        );
      })}
    </ol>
  );
}

function ClientDetails({ restaurant, ticket }) {
  const clientFields = [
    ["Identificador", restaurant.id],
    ["Responsável", restaurant.owner_name],
    ["Solicitante", restaurant.requester_name],
    ["E-mail", restaurant.email, true],
    ["WhatsApp", restaurant.whatsapp],
    ["Status da conta", restaurant.status ? <StatusBadge status={restaurant.status} /> : null],
  ];
  const ticketFields = [
    ["Ticket", ticket.number],
    ["Categoria", SUPPORT_CATEGORIES[ticket.category]],
    ["Assunto", ticket.subject, true],
    ["Abertura", formatSupportDate(ticket.created_at)],
    ["Última atividade", formatSupportDate(ticket.updated_at)],
    ["Atendimento", <TicketStatus status={ticket.status} staff />],
  ];
  return (
    <aside className="dh-card min-w-0 self-start" aria-label="Dados do restaurante" data-testid="support-client-details">
      <div className="border-b border-[var(--dh-border-soft)] px-5 py-5 sm:px-6">
        <h2 className="dh-font-display text-xl font-bold text-[var(--dh-text)]">Dados do restaurante</h2>
        <p className="mt-2 text-base font-semibold leading-snug text-[var(--dh-muted-strong)] [overflow-wrap:anywhere]">{restaurant.name || "—"}</p>
      </div>
      <div className="space-y-5 px-5 py-5 sm:px-6">
        <DetailsList fields={clientFields} />
        {restaurant.id && (
          <Link to={`/clientes/${restaurant.id}`} className="dh-btn dh-btn-outline min-h-11 w-full">
            Abrir cadastro <ArrowUpRight size={17} aria-hidden />
          </Link>
        )}
      </div>
      <div className="border-t border-[var(--dh-border-soft)] px-5 py-5 sm:px-6">
        <h3 className="dh-font-display mb-4 text-lg font-bold text-[var(--dh-text)]">Dados do ticket</h3>
        <DetailsList fields={ticketFields} />
      </div>
    </aside>
  );
}

function DetailsList({ fields }) {
  return (
    <dl className="grid gap-x-5 gap-y-4 sm:grid-cols-2 lg:grid-cols-1 2xl:grid-cols-2">
      {fields.map(([label, value, fullRow]) => (
        <div className={fullRow ? "min-w-0 col-span-full" : "min-w-0"} key={label}>
          <dt className="text-xs font-medium text-[var(--dh-muted)]">{label}</dt>
          <dd className="mt-1 text-sm font-medium text-[var(--dh-text)] [overflow-wrap:anywhere]">{value || "—"}</dd>
        </div>
      ))}
    </dl>
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
  const composer = useRef(null);
  const restoreComposerFocus = useRef(false);
  const olderScroll = useRef(null);
  const submitting = useRef(false);
  const messageAttempt = useRef(null);
  const statusAttempt = useRef(null);
  const readThrough = useRef(0);

  useLayoutEffect(() => {
    const input = composer.current;
    if (!input) return;
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 144)}px`;
  }, [text, thread?.ticket.status]);

  useEffect(() => {
    if (!busy && restoreComposerFocus.current) {
      restoreComposerFocus.current = false;
      composer.current?.focus();
    }
  }, [busy]);

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
      restoreComposerFocus.current = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
    });
  };
  const handleComposerKeyDown = (event) => {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing || event.keyCode === 229) return;
    if (!window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;
    event.preventDefault();
    if (!submitting.current && !busy && text.trim()) event.currentTarget.form.requestSubmit();
  };
  const changeStatus = (status) => mutate("status", { status }, statusAttempt, () => setResolving(false));

  return (
    <div className="w-full min-w-0 space-y-5 sm:space-y-6 dh-fade-in" data-testid="support-conversation-page">
      <Link to={basePath} className="dh-btn dh-btn-ghost min-h-11"><ArrowLeft size={18} aria-hidden /> Voltar aos tickets</Link>
      <SupportError error={loadError} retry={load} />
      {!thread && !loadError && <SupportLoading />}
      {thread && (
        <>
          <div className={`grid min-w-0 gap-5 xl:gap-7 ${staff ? "lg:grid-cols-[minmax(0,7fr)_minmax(14rem,3fr)] xl:grid-cols-[minmax(0,11fr)_minmax(0,4fr)]" : ""}`} data-testid="support-conversation-workspace">
            <div className="min-w-0 space-y-5 sm:space-y-6" data-testid="support-conversation-main">
              <header className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0 flex-1 basis-60 space-y-2.5">
                  <div className="flex flex-wrap items-center gap-2.5">
                    <span className="font-mono text-[13px] font-semibold text-[var(--dh-muted)] [overflow-wrap:anywhere]">{thread.ticket.number}</span>
                    <TicketStatus status={thread.ticket.status} staff={staff} testId="support-ticket-status" />
                  </div>
                  <h1 className="dh-font-display text-3xl font-bold tracking-tight text-[var(--dh-text)] [overflow-wrap:anywhere] sm:text-4xl" data-testid="support-ticket-title">{thread.ticket.subject}</h1>
                  <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[15px] text-[var(--dh-muted)]">
                    <span>{SUPPORT_CATEGORIES[thread.ticket.category]}</span>
                    <span>Aberto em <time dateTime={thread.ticket.created_at}>{formatSupportDate(thread.ticket.created_at)}</time></span>
                  </p>
                </div>
                {thread.ticket.status === "resolved" ? (
                  <button type="button" className="dh-btn dh-btn-outline min-h-11 disabled:opacity-50" disabled={!!busy} onClick={() => changeStatus("awaiting_support")} data-testid="support-reopen">
                    <RotateCcw size={17} aria-hidden /> Reabrir ticket
                  </button>
                ) : staff && (
                  <button type="button" className="dh-btn dh-btn-outline min-h-11 disabled:opacity-50" disabled={!!busy} onClick={() => setResolving(true)} data-testid="support-resolve">
                    <Check size={18} aria-hidden /> Marcar como resolvido
                  </button>
                )}
              </header>

              <section className="dh-card flex h-[clamp(27rem,74dvh,52rem)] min-w-0 flex-col sm:h-[clamp(28rem,calc(100dvh-22rem),52rem)]" aria-label="Conversa">
                <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-5 sm:px-6 sm:py-6 lg:px-8" ref={scroller}
                  onScroll={(event) => {
                    const { scrollHeight, clientHeight, scrollTop } = event.currentTarget;
                    setPinned(scrollHeight - clientHeight - scrollTop < 50);
                  }}>
                  {thread.next_before && (
                    <div className="mb-5 text-center">
                      <button className="dh-btn dh-btn-outline min-h-11 disabled:opacity-50" type="button" disabled={olderBusy} onClick={loadOlder} data-testid="support-load-older">
                        {olderBusy ? "Carregando…" : "Carregar mensagens anteriores"}
                      </button>
                    </div>
                  )}
                  <SupportError error={historyError} />
                  <ConversationHistory messages={thread.messages} staff={staff} />
                </div>
                {!pinned && (
                  <div className="px-4 pb-2 sm:px-6 lg:px-8">
                    <button type="button" className="dh-btn dh-btn-ghost" onClick={() => setPinned(true)}>Ir para mensagens recentes</button>
                  </div>
                )}
                <div className="grid shrink-0 gap-3 border-t border-[var(--dh-border-soft)] px-4 py-3 sm:px-6 lg:px-8">
                  <SupportError error={mutationError} />
                  {thread.ticket.status === "resolved" ? (
                    <p className="py-1 text-[15px] text-[var(--dh-muted)]">Reabra o ticket para continuar a conversa.</p>
                  ) : (
                    <form className="flex min-w-0 items-end gap-3" onSubmit={send}>
                      <label className="min-w-0 flex-1">
                        <span className="sr-only">Mensagem</span>
                        <textarea ref={composer} rows={1} className="dh-input block min-h-12 max-h-36 w-full resize-none overflow-y-auto leading-relaxed" value={text} onChange={(event) => setText(event.target.value)} onKeyDown={handleComposerKeyDown}
                          placeholder="Escreva uma mensagem..." required maxLength={4000} disabled={!!busy} data-testid="support-reply-input" />
                      </label>
                      <button className="dh-btn dh-btn-primary h-12 w-12 shrink-0" type="submit" disabled={!!busy || !text.trim()} aria-label="Enviar mensagem" data-testid="support-send-reply">
                        <Send size={17} aria-hidden />
                      </button>
                    </form>
                  )}
                </div>
              </section>
            </div>
            {staff && thread.restaurant && <ClientDetails restaurant={thread.restaurant} ticket={thread.ticket} />}
          </div>

          <AlertDialog open={resolving} onOpenChange={(next) => { if (!submitting.current) setResolving(next); }}>
            <AlertDialogContent className="max-w-[min(34rem,calc(100vw-2rem))] border-[var(--dh-border)] bg-[var(--dh-surface)] text-[var(--dh-text)] sm:p-7">
              <AlertDialogTitle className="dh-font-display text-2xl">Marcar ticket como resolvido?</AlertDialogTitle>
              <AlertDialogDescription className="text-[var(--dh-muted)]">O restaurante receberá uma notificação e poderá reabrir o ticket.</AlertDialogDescription>
              <SupportError error={mutationError} />
              <div className="flex flex-wrap justify-end gap-3">
                <AlertDialogCancel asChild><button className="dh-btn dh-btn-outline min-h-11" type="button" disabled={!!busy}>Cancelar</button></AlertDialogCancel>
                <button type="button" className="dh-btn dh-btn-primary min-h-11" disabled={!!busy} onClick={() => changeStatus("resolved")} data-testid="support-confirm-resolve">
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
