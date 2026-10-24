import { useCallback, useEffect, useRef, useState } from "react";
import { Navigate } from "react-router-dom";
import { CheckCircle2, CircleOff, LoaderCircle, Phone, RefreshCw, ShieldCheck, TriangleAlert } from "lucide-react";
import { api, formatApiErrorDetail } from "@/lib/api";
import { canStartAccountSwitch, clearedAccountSwitchDraft } from "@/lib/accountSwitchForm";
import { createLatestRequestGate } from "@/lib/latestRequest";
import { useAuth } from "@/context/AuthContext";

const CONNECTION_STATES = {
  open: { label: "Conectado", tone: "success", description: "A sessão WhatsApp está ativa no gateway." },
  connecting: { label: "Conectando", tone: "warning", description: "O gateway está tentando estabelecer a conexão." },
  pairing: { label: "Aguardando pareamento", tone: "warning", description: "A conta ainda aguarda uma vinculação autorizada." },
  disconnected: { label: "Desconectado", tone: "error", description: "A sessão perdeu a conexão e o gateway tentará recuperá-la." },
  logged_out: { label: "Sessão encerrada", tone: "error", description: "A sessão WhatsApp foi encerrada e exige um novo pareamento controlado." },
  error: { label: "Erro de conexão", tone: "error", description: "O gateway encontrou uma falha ao manter a sessão." },
  stopped: { label: "Serviço parado", tone: "neutral", description: "O processo do Baileys não está em execução." },
  disabled: { label: "Integração desativada", tone: "neutral", description: "O gateway está em modo de manutenção." },
  unavailable: { label: "Indisponível", tone: "neutral", description: "Não foi possível consultar o gateway com segurança." },
};

function connectionDetails(status) {
  return CONNECTION_STATES[status?.connection_state] || CONNECTION_STATES.unavailable;
}

function formatConnectedBrazilianPhone(phone) {
  const digits = typeof phone === "string" ? phone.replace(/\D/g, "") : "";
  if (!/^55[1-9]\d{9,10}$/.test(digits)) return "Número não disponível";
  const ddd = digits.slice(2, 4);
  const subscriber = digits.slice(4);
  const splitAt = subscriber.length === 9 ? 5 : 4;
  return "+55 (" + ddd + ") " + subscriber.slice(0, splitAt) + "-" + subscriber.slice(splitAt);
}

function StatusChip({ tone, children, className = "" }) {
  return <span className={`dh-chip dh-chip-${tone} dh-chip-dot ${className}`}>{children}</span>;
}

// This page deliberately renders no QR image. Linking codes exist only during a
// controlled, explicitly enabled window and remain solely in React memory.
export default function WhatsAppPairing() {
  const { user } = useAuth();
  const [status, setStatus] = useState(null);
  const [statusError, setStatusError] = useState("");
  const [statusLoading, setStatusLoading] = useState(true);
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [switchOpen, setSwitchOpen] = useState(false);
  const [switchPhone, setSwitchPhone] = useState("");
  const [switchPassword, setSwitchPassword] = useState("");
  const [switchConfirm, setSwitchConfirm] = useState(false);
  const [switchOperation, setSwitchOperation] = useState(null);
  const [switchState, setSwitchState] = useState("");
  const [switchCode, setSwitchCode] = useState("");
  const [switchError, setSwitchError] = useState("");
  const [switchBusy, setSwitchBusy] = useState(false);
  const statusRequestGate = useRef(null);
  if (!statusRequestGate.current) statusRequestGate.current = createLatestRequestGate();

  const loadStatus = useCallback(async () => {
    const requestId = statusRequestGate.current.begin();
    if (statusRequestGate.current.isCurrent(requestId)) {
      setStatusLoading(true);
      setStatusError("");
    }
    try {
      const { data } = await api.get("/hub/whatsapp/status");
      if (statusRequestGate.current.isCurrent(requestId)) setStatus(data);
    } catch {
      if (statusRequestGate.current.isCurrent(requestId)) {
        setStatus({ connection_state: "unavailable", gateway_reachable: false, pairing_self_service_enabled: false });
        setStatusError("Não foi possível consultar o status do gateway neste momento.");
      }
    } finally {
      if (statusRequestGate.current.isCurrent(requestId)) setStatusLoading(false);
    }
  }, []);

  useEffect(() => {
    if (user?.role === "super_admin") void loadStatus();
  }, [loadStatus, user?.role]);

  if (user?.role !== "super_admin") return <Navigate to="/painel" replace />;

  const connection = connectionDetails(status);
  const pairingEnabled = status?.pairing_self_service_enabled === true;
  const switchAvailable = status?.account_switch_available === true;
  const canStartSwitch = canStartAccountSwitch({
    phone: switchPhone, password: switchPassword, available: switchAvailable, busy: switchBusy,
  });

  function closeUnstartedSwitch() {
    if (switchOperation || switchBusy) return;
    const cleared = clearedAccountSwitchDraft();
    setSwitchOpen(false);
    setSwitchPhone(cleared.phone);
    setSwitchPassword(cleared.password);
    setSwitchConfirm(cleared.confirm);
    setSwitchCode(cleared.code);
    setSwitchState(cleared.state);
    setSwitchError(cleared.error);
  }

  async function refreshSwitch(operationId = switchOperation) {
    if (!operationId) return;
    try {
      const { data } = await api.get(`/hub/whatsapp/account-switch/${operationId}`);
      setSwitchState(data.state || "unavailable");
      if (data.state === "promoted") {
        setSwitchOperation(null); setSwitchCode(""); setSwitchOpen(false);
        void loadStatus();
      }
    } catch { setSwitchState("unavailable"); }
  }

  async function startSwitch(event) {
    event.preventDefault();
    setSwitchBusy(true); setSwitchError(""); setSwitchCode("");
    try {
      const { data } = await api.post("/hub/whatsapp/account-switch", {
        // Starting a candidate never replaces the active account. The explicit
        // confirmation remains exclusively on the irreversible promotion.
        phone: switchPhone, password: switchPassword, confirm: true,
      });
      setSwitchOperation(data.operation_id); setSwitchState(data.state || "preparing"); setSwitchPassword(""); setSwitchConfirm(false);
      await refreshSwitch(data.operation_id);
    } catch (requestError) {
      setSwitchError(formatApiErrorDetail(requestError.response?.data?.detail) || "Não foi possível iniciar a troca segura.");
    } finally { setSwitchBusy(false); }
  }

  async function requestSwitchCode() {
    if (!switchOperation) return;
    setSwitchBusy(true); setSwitchError("");
    try {
      const { data } = await api.post(`/hub/whatsapp/account-switch/${switchOperation}/code`);
      setSwitchCode(data.code || ""); setSwitchState(data.state || switchState);
    } catch (requestError) {
      setSwitchError(formatApiErrorDetail(requestError.response?.data?.detail) || "O código ainda não está disponível.");
      void refreshSwitch();
    } finally { setSwitchBusy(false); }
  }

  async function cancelSwitch() {
    if (!switchOperation) return;
    setSwitchBusy(true); setSwitchError("");
    try {
      await api.post(`/hub/whatsapp/account-switch/${switchOperation}/cancel`);
      setSwitchOperation(null); setSwitchCode(""); setSwitchState(""); setSwitchOpen(false); setSwitchConfirm(false);
    } catch (requestError) {
      setSwitchError(formatApiErrorDetail(requestError.response?.data?.detail) || "Não foi possível cancelar a troca.");
    } finally { setSwitchBusy(false); }
  }

  async function promoteSwitch(event) {
    event.preventDefault();
    if (!switchOperation) return;
    setSwitchBusy(true); setSwitchError("");
    try {
      await api.post(`/hub/whatsapp/account-switch/${switchOperation}/promote`, { password: switchPassword, confirm: switchConfirm });
      setSwitchState("promoted"); setSwitchPassword(""); setSwitchCode(""); setSwitchOperation(null); setSwitchOpen(false); setSwitchConfirm(false);
      await loadStatus();
    } catch (requestError) {
      setSwitchError(formatApiErrorDetail(requestError.response?.data?.detail) || "A substituição ainda não pode ser concluída.");
      void refreshSwitch();
    } finally { setSwitchBusy(false); }
  }

  async function submit(event) {
    event.preventDefault();
    setBusy(true); setError(""); setCode("");
    try {
      const { data } = await api.post("/hub/whatsapp/pairing-code", { phone, password });
      setCode(data.code || "");
      setPassword("");
    } catch (requestError) {
      setError(formatApiErrorDetail(requestError.response?.data?.detail) || "Pareamento temporariamente indisponível.");
      void loadStatus();
    } finally { setBusy(false); }
  }

  return (
    <section className="w-full py-6 sm:py-10 space-y-6 lg:min-h-[calc(100dvh-5rem)] lg:flex lg:flex-col">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="text-[11px] uppercase tracking-widest font-bold text-[var(--dh-accent)] mb-3">Administração restrita</div>
          <h1 className="text-3xl font-bold text-[var(--dh-text)]" style={{ fontFamily: "Cabinet Grotesk" }}>Integração WhatsApp</h1>
          <p className="text-sm text-[var(--dh-muted)] mt-3 max-w-2xl">Acompanhe a integração de mensagens transacionais do DACOT. Uma conexão ativa não confirma a entrega individual de mensagens.</p>
        </div>
        <button
          type="button"
          className="dh-btn dh-btn-outline shrink-0"
          onClick={() => void loadStatus()}
          disabled={statusLoading}
          data-testid="whatsapp-status-refresh"
        >
          <RefreshCw size={16} strokeWidth={1.75} className={statusLoading ? "animate-spin" : ""} />
          Atualizar status
        </button>
      </div>

      {statusError && <div className="dh-chip dh-chip-warning" role="status">{statusError}</div>}

      <div className="grid gap-6 lg:min-h-0 lg:flex-1 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] lg:items-stretch">
        <article className="dh-card flex h-full flex-col p-6 sm:p-8 lg:p-10" data-testid="whatsapp-connected-account">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="dh-kpi-label text-[13px] sm:text-sm">Conta WhatsApp</p>
              <h2 className="mt-3 text-3xl font-semibold leading-tight text-[var(--dh-text)] sm:text-4xl lg:text-[clamp(2.25rem,3vw,3.5rem)]">{formatConnectedBrazilianPhone(status?.connected_account_phone)}</h2>
            </div>
            <Phone size={32} strokeWidth={1.65} className="shrink-0 text-[var(--dh-accent)]" />
          </div>
          <p className="mt-5 max-w-xl text-base leading-relaxed text-[var(--dh-muted)] sm:text-lg">
            {status?.connected_account_phone ? "Número da conta ativa reconhecida pelo gateway." : "O gateway não informou um número confiável para a sessão atual."}
          </p>

          <div className="mt-auto border-t border-[var(--dh-border-soft)] pt-7 sm:pt-9">
            {switchOpen && !switchOperation ? (
              <button type="button" className="dh-btn dh-btn-outline w-full py-4 text-base sm:text-lg" disabled={switchBusy}
                      onClick={closeUnstartedSwitch} data-testid="whatsapp-account-switch-close">
                Cancelar troca
              </button>
            ) : (
              <button type="button" className="dh-btn dh-btn-outline w-full py-4 text-base sm:text-lg" disabled={!switchAvailable || switchBusy}
                      onClick={() => { setSwitchOpen(true); setSwitchError(""); }} data-testid="whatsapp-account-switch-open">
                Trocar número do WhatsApp
              </button>
            )}
            <p className="mt-4 text-sm leading-relaxed text-[var(--dh-muted)]">{switchAvailable ? "A troca mantém a conta atual ativa até a confirmação final." : "A troca segura está indisponível enquanto o gateway não estiver configurado."}</p>
            {switchOpen && !switchOperation && (
              <form onSubmit={startSwitch} className="mt-6 space-y-4 border-t border-[var(--dh-border-soft)] pt-6" autoComplete="off">
                <label className="block text-sm text-[var(--dh-text)]">Novo número WhatsApp
                  <input className="dh-input mt-2" type="tel" inputMode="numeric" required value={switchPhone} onChange={(event) => setSwitchPhone(event.target.value)} placeholder="(11) 99999-9999" data-testid="whatsapp-account-switch-phone" />
                </label>
                <label className="block text-sm text-[var(--dh-text)]">Confirme sua senha de superadministrador
                  <input className="dh-input mt-2" type="password" required value={switchPassword} onChange={(event) => setSwitchPassword(event.target.value)} autoComplete="current-password" data-testid="whatsapp-account-switch-password" />
                </label>
                {switchError && <div className="dh-chip dh-chip-error" role="alert">{switchError}</div>}
                <button type="submit" className="dh-btn dh-btn-primary w-full" disabled={!canStartSwitch}>{switchBusy ? "Preparando…" : "Iniciar troca segura"}</button>
              </form>
            )}
            {switchOpen && switchOperation && (
              <div className="mt-6 space-y-4 border-t border-[var(--dh-border-soft)] pt-6" data-testid="whatsapp-account-switch-operation">
                <p className="text-sm text-[var(--dh-muted)]">Estado da nova conta: <strong className="text-[var(--dh-text)]">{switchState || "consultando"}</strong></p>
                {switchCode ? <output className="block rounded-lg border border-[var(--dh-border)] bg-[var(--dh-surface-secondary)] p-4 text-center font-mono text-2xl tracking-[0.2em] text-[var(--dh-text)]" aria-live="polite">{switchCode}</output> :
                  <button type="button" className="dh-btn dh-btn-outline w-full" onClick={() => void requestSwitchCode()} disabled={switchBusy}>Obter código de vinculação</button>}
                <button type="button" className="dh-btn dh-btn-outline w-full" onClick={() => void refreshSwitch()} disabled={switchBusy}>Atualizar estado da nova conta</button>
                {switchState === "ready" && <form onSubmit={promoteSwitch} className="space-y-3">
                  <label className="block text-sm text-[var(--dh-text)]">Confirme novamente sua senha para substituir a conta
                    <input className="dh-input mt-2" type="password" required value={switchPassword} onChange={(event) => setSwitchPassword(event.target.value)} autoComplete="current-password" />
                  </label>
                  <label className="flex items-start gap-3 text-sm text-[var(--dh-muted)]"><input type="checkbox" checked={switchConfirm} onChange={(event) => setSwitchConfirm(event.target.checked)} required />Confirmo a substituição definitiva da conta atual.</label>
                  <button type="submit" className="dh-btn dh-btn-primary w-full" disabled={switchBusy || !switchConfirm}>Confirmar substituição</button>
                </form>}
                {switchError && <div className="dh-chip dh-chip-error" role="alert">{switchError}</div>}
                <button type="button" className="dh-btn dh-btn-outline w-full" onClick={() => void cancelSwitch()} disabled={switchBusy}>Cancelar troca</button>
              </div>
            )}
          </div>
        </article>

        <div className="grid gap-5 sm:grid-cols-2 lg:h-full lg:min-h-0 lg:grid-rows-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
          <article className="dh-card flex h-full flex-col p-6 sm:p-7 lg:p-8" data-testid="whatsapp-connection-status">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="dh-kpi-label text-[13px] sm:text-sm">Conexão WhatsApp</p>
                <h2 className="mt-3 text-xl font-semibold text-[var(--dh-text)] sm:text-2xl lg:text-[clamp(1.4rem,1.65vw,2rem)]">{connection.label}</h2>
              </div>
              {connection.tone === "success" ? <CheckCircle2 size={28} strokeWidth={1.65} className="shrink-0 text-[var(--dh-success-fg)]" /> : <CircleOff size={28} strokeWidth={1.65} className="shrink-0 text-[var(--dh-muted)]" />}
            </div>
            <p className="mt-4 text-sm leading-relaxed text-[var(--dh-muted)] sm:text-base">{connection.description}</p>
            <div className="mt-auto pt-6">
              {statusLoading ? <StatusChip tone="neutral" className="px-3 py-1 text-sm sm:text-[15px]"><LoaderCircle size={15} className="animate-spin" /> Consultando</StatusChip> : <StatusChip tone={connection.tone} className="px-3 py-1 text-sm sm:text-[15px]">{connection.label}</StatusChip>}
            </div>
          </article>

          <article className="dh-card flex h-full flex-col p-6 sm:p-7 lg:p-8" data-testid="whatsapp-gateway-status">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="dh-kpi-label text-[13px] sm:text-sm">Serviço gateway</p>
                <h2 className="mt-3 text-xl font-semibold text-[var(--dh-text)] sm:text-2xl lg:text-[clamp(1.4rem,1.65vw,2rem)]">{status?.gateway_reachable ? "Gateway disponível" : "Gateway indisponível"}</h2>
              </div>
              {status?.gateway_reachable ? <ShieldCheck size={28} strokeWidth={1.65} className="shrink-0 text-[var(--dh-success-fg)]" /> : <TriangleAlert size={28} strokeWidth={1.65} className="shrink-0 text-[var(--dh-warning-fg)]" />}
            </div>
            <p className="mt-4 text-sm leading-relaxed text-[var(--dh-muted)] sm:text-base">{status?.gateway_reachable ? "O HUB recebeu uma resposta autenticada do gateway." : "O HUB não recebeu uma resposta autenticada do gateway."}</p>
            <div className="mt-auto pt-6">
              <StatusChip tone={status?.gateway_reachable ? "success" : "neutral"} className="px-3 py-1 text-sm sm:text-[15px]">{status?.gateway_reachable ? "Disponível" : "Indisponível"}</StatusChip>
            </div>
          </article>

          <article className="dh-card flex h-full flex-col p-7 sm:col-span-2 sm:p-9 lg:p-10" data-testid="whatsapp-pairing-panel">
            <div className="flex items-start gap-3">
              <ShieldCheck size={30} strokeWidth={1.65} className="mt-0.5 shrink-0 text-[var(--dh-accent)]" />
              <div>
                <p className="dh-kpi-label text-[13px] sm:text-sm">Pareamento administrativo</p>
                <h2 className="mt-2 text-2xl font-semibold text-[var(--dh-text)] sm:text-3xl lg:text-[clamp(1.75rem,2.1vw,2.6rem)]">{pairingEnabled ? "Pareamento habilitado" : "Pareamento bloqueado"}</h2>
                <p className="mt-4 max-w-2xl text-sm leading-relaxed text-[var(--dh-muted)] sm:text-base">{pairingEnabled ? "A geração de código está disponível nesta janela controlada." : "A geração de novos códigos permanece desativada. A sessão atual não será alterada."}</p>
              </div>
            </div>

            {pairingEnabled && (code ? (
              <div className="mt-auto rounded-lg border border-[var(--dh-border)] bg-[var(--dh-surface-secondary)] p-6 space-y-4" data-testid="whatsapp-pairing-code">
                <p className="text-base text-[var(--dh-muted)]">Digite este código no WhatsApp da conta de serviço. Ele é mostrado somente nesta sessão do navegador.</p>
                <output className="block text-center font-mono text-3xl tracking-[0.25em] text-[var(--dh-text)] sm:text-4xl" aria-live="polite">{code}</output>
              </div>
            ) : (
              <form onSubmit={submit} className="mt-auto space-y-6 pt-8" autoComplete="off">
                <label className="block text-sm text-[var(--dh-text)]">Número da conta WhatsApp DACOT
                  <input className="dh-input mt-2 py-3 text-base" type="tel" inputMode="numeric" required value={phone}
                         onChange={(event) => setPhone(event.target.value)} placeholder="(11) 99999-9999"
                         data-testid="whatsapp-pairing-phone" />
                </label>
                <label className="block text-sm text-[var(--dh-text)]">Confirme sua senha de superadministrador
                  <input className="dh-input mt-2 py-3 text-base" type="password" required value={password}
                         onChange={(event) => setPassword(event.target.value)} autoComplete="current-password"
                         data-testid="whatsapp-pairing-password" />
                </label>
                {error && <div className="dh-chip dh-chip-error" role="alert">{error}</div>}
                <button type="submit" className="dh-btn dh-btn-primary w-full py-4 text-base font-semibold sm:text-lg" disabled={busy} data-testid="whatsapp-pairing-submit">
                  {busy ? "Solicitando…" : "Gerar código de vinculação"}
                </button>
              </form>
            ))}
          </article>
        </div>
      </div>
    </section>
  );
}
