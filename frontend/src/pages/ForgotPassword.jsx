import { useState } from "react";
import { Link } from "react-router-dom";
import { api, formatApiErrorDetail } from "@/lib/api";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      await api.post("/auth/forgot-password", { email: email.trim() });
      setDone(true);
    } catch (e) {
      setErr(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    } finally { setBusy(false); }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-6 bg-[var(--dh-bg)]">
      <div className="dh-card p-8 w-full max-w-md">
        <div className="text-[11px] uppercase tracking-widest font-bold text-[var(--dh-accent)] mb-2">Recuperação</div>
        <h1 className="text-3xl font-black mb-3" style={{fontFamily:"Cabinet Grotesk"}}>Redefinir senha</h1>
        {done ? (
          <>
            <p className="text-[14px] text-[var(--dh-muted)] mb-6">
              Se este e-mail estiver cadastrado, enviaremos um link de redefinição em instantes.
            </p>
            <Link to="/login" className="dh-btn dh-btn-outline w-full" data-testid="back-to-login">Voltar ao login</Link>
          </>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <p className="text-[14px] text-[var(--dh-muted)]">
              Informe o e-mail da sua conta DACOT Hub. Enviaremos um link de recuperação.
            </p>
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
                   className="dh-input" placeholder="voce@dacot.com" data-testid="forgot-email" />
            {err && <div className="dh-chip dh-chip-error">{err}</div>}
            <button type="submit" className="dh-btn dh-btn-primary w-full" disabled={busy} data-testid="forgot-submit">
              {busy ? "Enviando…" : "Enviar link"}
            </button>
            <Link to="/login" className="block text-center text-[12px] uppercase tracking-widest font-bold text-[var(--dh-muted)] hover:text-[var(--dh-text)]">
              Voltar ao login
            </Link>
          </form>
        )}
      </div>
    </div>
  );
}
