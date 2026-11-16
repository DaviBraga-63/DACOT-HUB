import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Eye, EyeOff } from "lucide-react";
import { api, formatApiErrorDetail } from "@/lib/api";

export default function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const nav = useNavigate();
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [firstAccess, setFirstAccess] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let current = true;
    if (!token) return undefined;
    api.post("/auth/reset-password/context", { token })
      .then(({ data }) => {
        if (current) setFirstAccess(data?.first_access === true);
      })
      .catch(() => {
        if (current) setFirstAccess(false);
      });
    return () => { current = false; };
  }, [token]);

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
      <div className="dh-card p-8 w-full max-w-md dh-fade-in">
        <div className="text-[11px] uppercase tracking-widest font-bold text-[var(--dh-accent)] mb-3">Nova Senha</div>
        <h1 className="text-3xl font-bold mb-6" style={{fontFamily:"Cabinet Grotesk"}}>Escolha uma nova senha</h1>
        <form onSubmit={submit} className="space-y-5">
          <div>
            <label className="block text-[13px] font-semibold text-slate-700 mb-2">Senha</label>
            <div className="relative">
              <button
                type="button"
                onClick={() => setShowPassword((visible) => !visible)}
                className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-[var(--dh-muted)] transition-colors hover:text-[var(--dh-accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--dh-accent)] focus-visible:ring-inset"
                aria-label={showPassword ? "Ocultar senha" : "Mostrar senha"}
                data-testid="toggle-reset-password-visibility"
              >
                {showPassword ? <Eye size={18} aria-hidden="true" /> : <EyeOff size={18} aria-hidden="true" />}
              </button>
              <input
                type={showPassword ? "text" : "password"}
                minLength={6}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="dh-input pr-10"
                placeholder="Mínimo 6 caracteres"
                data-testid="reset-password"
              />
            </div>
          </div>
          {err && <div className="dh-chip dh-chip-error">{err}</div>}
          <button type="submit" className="dh-btn dh-btn-primary w-full py-3 font-semibold" disabled={busy} data-testid="reset-submit">
            {busy ? "Salvando…" : (firstAccess ? "Criar senha" : "Redefinir senha")}
          </button>
          <Link to="/login" className="block text-center text-[12px] uppercase tracking-widest font-bold text-slate-500 hover:text-slate-700 transition-colors">
            Voltar ao login
          </Link>
        </form>
      </div>
    </div>
  );
}
