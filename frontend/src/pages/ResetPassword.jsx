import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, formatApiErrorDetail } from "@/lib/api";

export default function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const nav = useNavigate();
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    if (!token) { setErr("Token de redefinição inválido."); return; }
    setBusy(true); setErr(null);
    try {
      await api.post("/auth/reset-password", { token, password });
      nav("/login", { replace: true });
    } catch (e) {
      setErr(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    } finally { setBusy(false); }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-6 bg-[var(--dh-bg)]">
      <div className="dh-card p-8 w-full max-w-md">
        <div className="text-[11px] uppercase tracking-widest font-bold text-[var(--dh-accent)] mb-2">Nova senha</div>
        <h1 className="text-3xl font-black mb-3" style={{fontFamily:"Cabinet Grotesk"}}>Escolha uma nova senha</h1>
        <form onSubmit={submit} className="space-y-4">
          <input type="password" minLength={6} required value={password} onChange={(e) => setPassword(e.target.value)}
                 className="dh-input" placeholder="Mínimo 6 caracteres" data-testid="reset-password" />
          {err && <div className="dh-chip dh-chip-error">{err}</div>}
          <button type="submit" className="dh-btn dh-btn-primary w-full" disabled={busy} data-testid="reset-submit">
            {busy ? "Salvando…" : "Redefinir senha"}
          </button>
          <Link to="/login" className="block text-center text-[12px] uppercase tracking-widest font-bold text-[var(--dh-muted)] hover:text-[var(--dh-text)]">
            Voltar ao login
          </Link>
        </form>
      </div>
    </div>
  );
}
