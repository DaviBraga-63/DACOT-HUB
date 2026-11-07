import { useCallback, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { LoaderCircle, MessageCircle, RefreshCw } from "lucide-react";
import { api, formatApiErrorDetail } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

const STATUS = {
  open: "Conectado",
  connecting: "Conectando",
  pairing: "Aguardando pareamento",
  disconnected: "Desconectado",
  logged_out: "Sessão encerrada",
  error: "Erro de conexão",
  stopped: "Serviço parado",
  disabled: "Integração desativada",
  unavailable: "Indisponível",
};

export default function WhatsAppIntegration() {
  const { user } = useAuth();
  const [status, setStatus] = useState(null);
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/hub/whatsapp/status");
      setStatus(data);
    } catch {
      setStatus({ connection_state: "unavailable", gateway_reachable: false, pairing_enabled: false });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void loadStatus(); }, [loadStatus]);
  if (user?.role !== "super_admin") return <Navigate to="/painel" replace />;

  const requestCode = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    setCode("");
    try {
      const { data } = await api.post("/hub/whatsapp/pairing-code", { phone, password });
      setCode(data.code);
      setPassword("");
      await loadStatus();
    } catch (err) {
      setError(formatApiErrorDetail(err.response?.data?.detail) || "Não foi possível iniciar o pareamento.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-3xl space-y-6" data-testid="whatsapp-integration-page">
      <header>
        <div className="flex items-center gap-2 text-[12px] uppercase tracking-widest font-bold text-[var(--dh-accent)]">
          <MessageCircle size={15} /> Integração
        </div>
        <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-slate-900 mt-3 mb-2" style={{ fontFamily: "Cabinet Grotesk" }}>
          WhatsApp do Hub
        </h1>
        <p className="text-[15px] text-slate-500">Canal para links de primeiro acesso e recuperação de conta.</p>
      </header>

      <section className="dh-card p-6 space-y-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-[12px] uppercase tracking-widest font-bold text-[var(--dh-muted)]">Estado do gateway</div>
            <div className="mt-2 text-lg font-semibold text-[var(--dh-text)]">
              {loading ? "Consultando…" : STATUS[status?.connection_state] || STATUS.unavailable}
            </div>
          </div>
          <button type="button" onClick={() => void loadStatus()} className="dh-btn dh-btn-ghost" disabled={loading} aria-label="Atualizar estado">
            {loading ? <LoaderCircle size={16} className="animate-spin" /> : <RefreshCw size={16} />}
          </button>
        </div>
        {!status?.gateway_reachable && <p className="text-[13px] text-[var(--dh-muted)]">O serviço WhatsApp não respondeu. O primeiro acesso continuará disponível por e-mail.</p>}
      </section>

      {status?.pairing_enabled && status.connection_state === "logged_out" && (
        <p className="dh-chip dh-chip-warning">A sessão foi encerrada. Um operador deve reiniciar o pareamento pelo utilitário administrativo privado do serviço antes de solicitar um novo código.</p>
      )}

      {status?.connection_state === "error" && (
        <p className="dh-chip dh-chip-warning">As tentativas de reconexão foram esgotadas. Verifique os logs e o armazenamento do serviço e reinicie-o pelo painel; isso preserva a sessão. Só refaça o pareamento se o estado indicar que a sessão foi encerrada.</p>
      )}

      {status?.pairing_enabled && ["connecting", "pairing"].includes(status.connection_state) && (
        <section className="dh-card p-6 space-y-4">
          <div>
            <h2 className="text-lg font-semibold text-[var(--dh-text)]">Conectar ou reconectar número</h2>
            <p className="text-[13px] text-[var(--dh-muted)] mt-1">Confirme sua senha. O código é temporário e aparece somente nesta tela.</p>
          </div>
          <form onSubmit={requestCode} className="space-y-4">
            <label className="block text-[13px] font-medium text-slate-700">Celular WhatsApp
              <input type="tel" required minLength={10} maxLength={32} className="dh-input mt-1" value={phone} onChange={(event) => setPhone(event.target.value)} />
            </label>
            <label className="block text-[13px] font-medium text-slate-700">Senha do administrador DACOT
              <input type="password" required className="dh-input mt-1" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" />
            </label>
            {error && <p role="alert" className="dh-chip dh-chip-error">{error}</p>}
            <button type="submit" className="dh-btn dh-btn-primary" disabled={busy}>
              {busy ? "Solicitando…" : "Solicitar código de pareamento"}
            </button>
          </form>
          {code && <div className="rounded-xl border border-[var(--dh-border-soft)] p-4" role="status">
            <div className="text-[12px] text-[var(--dh-muted)]">Informe este código no WhatsApp do celular</div>
            <div className="mt-2 font-mono text-2xl font-bold tracking-widest" data-testid="whatsapp-pairing-code">{code}</div>
            <p className="mt-2 text-[12px] text-[var(--dh-muted)]">O código não é salvo. Não o compartilhe.</p>
          </div>}
        </section>
      )}
    </div>
  );
}
