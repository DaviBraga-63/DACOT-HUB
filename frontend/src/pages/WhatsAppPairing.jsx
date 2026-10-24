import { useCallback, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { CheckCircle2, CircleOff, LoaderCircle, Phone, RefreshCw, ShieldCheck, TriangleAlert } from "lucide-react";
import { api, formatApiErrorDetail } from "@/lib/api";
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

function StatusChip({ tone, children }) {
  return <span className={`dh-chip dh-chip-${tone} dh-chip-dot`}>{children}</span>;
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

  const loadStatus = useCallback(async () => {
    setStatusLoading(true);
    setStatusError("");
    try {
      const { data } = await api.get("/hub/whatsapp/status");
      setStatus(data);
    } catch {
      setStatus({ connection_state: "unavailable", gateway_reachable: false, pairing_self_service_enabled: false });
      setStatusError("Não foi possível consultar o status do gateway neste momento.");
    } finally {
      setStatusLoading(false);
    }
  }, []);

  useEffect(() => {
    if (user?.role === "super_admin") void loadStatus();
  }, [loadStatus, user?.role]);

  if (user?.role !== "super_admin") return <Navigate to="/painel" replace />;

  const connection = connectionDetails(status);
  const pairingEnabled = status?.pairing_self_service_enabled === true;

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
    <section className="max-w-5xl mx-auto py-6 sm:py-10 px-0 sm:px-6 space-y-5">
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

      <div className="grid gap-5 lg:grid-cols-2 lg:items-start">
        <article className="dh-card p-6 sm:p-8 space-y-6" data-testid="whatsapp-connected-account">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="dh-kpi-label">Conta WhatsApp</p>
              <h2 className="mt-2 text-xl font-semibold text-[var(--dh-text)]">{formatConnectedBrazilianPhone(status?.connected_account_phone)}</h2>
            </div>
            <Phone size={22} className="text-[var(--dh-accent)]" />
          </div>
          <p className="text-sm text-[var(--dh-muted)]">
            {status?.connected_account_phone ? "Número da conta ativa reconhecida pelo gateway." : "O gateway não informou um número confiável para a sessão atual."}
          </p>

          <div className="border-t border-[var(--dh-border-soft)] pt-5" data-testid="whatsapp-connection-status">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="dh-kpi-label">Estado da conexão</p>
                <h3 className="mt-2 text-lg font-semibold text-[var(--dh-text)]">{connection.label}</h3>
              </div>
              {connection.tone === "success" ? <CheckCircle2 size={22} className="text-[var(--dh-success-fg)]" /> : <CircleOff size={22} className="text-[var(--dh-muted)]" />}
            </div>
            <p className="mt-3 text-sm text-[var(--dh-muted)]">{connection.description}</p>
            <div className="mt-4">
              {statusLoading ? <StatusChip tone="neutral"><LoaderCircle size={13} className="animate-spin" /> Consultando</StatusChip> : <StatusChip tone={connection.tone}>{connection.label}</StatusChip>}
            </div>
          </div>

          <div className="border-t border-[var(--dh-border-soft)] pt-5">
            <button type="button" className="dh-btn dh-btn-outline w-full opacity-60 cursor-not-allowed" disabled aria-describedby="whatsapp-change-account-note">
              Trocar número do WhatsApp
            </button>
            <p id="whatsapp-change-account-note" className="mt-3 text-xs text-[var(--dh-muted)]">A troca segura de conta será disponibilizada em uma próxima etapa.</p>
          </div>
        </article>

        <div className="space-y-5">
          <article className="dh-card p-6" data-testid="whatsapp-gateway-status">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="dh-kpi-label">Serviço gateway</p>
                <h2 className="mt-2 text-lg font-semibold text-[var(--dh-text)]">{status?.gateway_reachable ? "Gateway disponível" : "Gateway indisponível"}</h2>
              </div>
              {status?.gateway_reachable ? <ShieldCheck size={22} className="text-[var(--dh-success-fg)]" /> : <TriangleAlert size={22} className="text-[var(--dh-warning-fg)]" />}
            </div>
            <p className="mt-3 text-sm text-[var(--dh-muted)]">{status?.gateway_reachable ? "O HUB recebeu uma resposta autenticada do gateway." : "O HUB não recebeu uma resposta autenticada do gateway."}</p>
            <div className="mt-4">
              <StatusChip tone={status?.gateway_reachable ? "success" : "neutral"}>{status?.gateway_reachable ? "Disponível" : "Indisponível"}</StatusChip>
            </div>
          </article>

          <article className="dh-card p-6 space-y-6" data-testid="whatsapp-pairing-panel">
            <div className="flex items-start gap-3">
              <ShieldCheck size={20} strokeWidth={1.75} className="mt-0.5 shrink-0 text-[var(--dh-accent)]" />
              <div>
                <p className="dh-kpi-label">Pareamento administrativo</p>
                <h2 className="mt-1 text-xl font-semibold text-[var(--dh-text)]">{pairingEnabled ? "Pareamento habilitado" : "Pareamento bloqueado"}</h2>
                <p className="mt-2 text-sm text-[var(--dh-muted)]">{pairingEnabled ? "A geração de código está disponível nesta janela controlada." : "A geração de novos códigos permanece desativada. A sessão atual não será alterada."}</p>
              </div>
            </div>

            {pairingEnabled && (code ? (
              <div className="rounded-lg border border-[var(--dh-border)] bg-[var(--dh-surface-secondary)] p-5 space-y-3" data-testid="whatsapp-pairing-code">
                <p className="text-sm text-[var(--dh-muted)]">Digite este código no WhatsApp da conta de serviço. Ele é mostrado somente nesta sessão do navegador.</p>
                <output className="block text-center font-mono text-3xl tracking-[0.25em] text-[var(--dh-text)]" aria-live="polite">{code}</output>
              </div>
            ) : (
              <form onSubmit={submit} className="space-y-5" autoComplete="off">
                <label className="block text-[13px] text-[var(--dh-text)]">Número da conta WhatsApp DACOT
                  <input className="dh-input mt-1" type="tel" inputMode="numeric" required value={phone}
                         onChange={(event) => setPhone(event.target.value)} placeholder="(11) 99999-9999"
                         data-testid="whatsapp-pairing-phone" />
                </label>
                <label className="block text-[13px] text-[var(--dh-text)]">Confirme sua senha de superadministrador
                  <input className="dh-input mt-1" type="password" required value={password}
                         onChange={(event) => setPassword(event.target.value)} autoComplete="current-password"
                         data-testid="whatsapp-pairing-password" />
                </label>
                {error && <div className="dh-chip dh-chip-error" role="alert">{error}</div>}
                <button type="submit" className="dh-btn dh-btn-primary w-full py-3 font-semibold" disabled={busy} data-testid="whatsapp-pairing-submit">
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
