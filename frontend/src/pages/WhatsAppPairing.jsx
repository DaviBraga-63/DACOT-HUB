import { useState } from "react";
import { Navigate } from "react-router-dom";
import { api, formatApiErrorDetail } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

// This page deliberately renders no QR image and stores the short-lived
// linking code only in React memory. The gateway never exposes its admin port.
export default function WhatsAppPairing() {
  const { user } = useAuth();
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (user?.role !== "super_admin") return <Navigate to="/painel" replace />;

  async function submit(event) {
    event.preventDefault();
    setBusy(true); setError(""); setCode("");
    try {
      const { data } = await api.post("/hub/whatsapp/pairing-code", { phone, password });
      setCode(data.code || "");
      setPassword("");
    } catch (requestError) {
      setError(formatApiErrorDetail(requestError.response?.data?.detail) || "Pareamento temporariamente indisponível.");
    } finally { setBusy(false); }
  }

  return (
    <section className="max-w-xl mx-auto py-10 px-6">
      <div className="dh-card p-8 space-y-6">
        <div>
          <div className="text-[11px] uppercase tracking-widest font-bold text-[var(--dh-accent)] mb-3">Administração restrita</div>
          <h1 className="text-3xl font-bold" style={{ fontFamily: "Cabinet Grotesk" }}>Vincular WhatsApp DACOT</h1>
          <p className="text-sm text-[var(--dh-muted)] mt-3">Gere um código de vinculação para informar no aplicativo WhatsApp da conta de serviço. O QR e as credenciais administrativas não são expostos por esta tela.</p>
        </div>
        {code ? (
          <div className="rounded-lg border border-[var(--dh-border)] bg-[var(--dh-surface-secondary)] p-5 space-y-3" data-testid="whatsapp-pairing-code">
            <p className="text-sm text-[var(--dh-muted)]">Digite este código no WhatsApp da conta de serviço. Ele é mostrado somente nesta sessão do navegador.</p>
            <output className="block text-center font-mono text-3xl tracking-[0.25em] text-[var(--dh-text)]" aria-live="polite">{code}</output>
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-5" autoComplete="off">
            <label className="block text-[13px]">Número da conta WhatsApp DACOT
              <input className="dh-input mt-1" type="tel" inputMode="numeric" required value={phone}
                     onChange={(event) => setPhone(event.target.value)} placeholder="(11) 99999-9999"
                     data-testid="whatsapp-pairing-phone" />
            </label>
            <label className="block text-[13px]">Confirme sua senha de superadministrador
              <input className="dh-input mt-1" type="password" required value={password}
                     onChange={(event) => setPassword(event.target.value)} autoComplete="current-password"
                     data-testid="whatsapp-pairing-password" />
            </label>
            {error && <div className="dh-chip dh-chip-error" role="alert">{error}</div>}
            <button type="submit" className="dh-btn dh-btn-primary w-full py-3 font-semibold" disabled={busy} data-testid="whatsapp-pairing-submit">
              {busy ? "Solicitando…" : "Gerar código de vinculação"}
            </button>
          </form>
        )}
      </div>
    </section>
  );
}
