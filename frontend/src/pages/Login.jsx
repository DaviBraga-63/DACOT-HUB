import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

export default function Login() {
  const { login, error, setError } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError(null);
    const data = await login(email.trim(), password);
    setBusy(false);
    if (data) navigate(data.user_type === "restaurant" ? "/portal" : "/", { replace: true });
  };

  return (
    <div className="min-h-screen grid grid-cols-1 lg:grid-cols-2 bg-[var(--dh-bg)]">
      {/* Left */}
      <div className="flex flex-col justify-between px-6 sm:px-10 lg:px-16 py-8 sm:py-12 lg:py-10">
        <div className="flex items-center gap-3">
          <div 
            className="w-10 h-10 rounded-lg flex items-center justify-center text-white font-bold shadow-md"
            style={{background: 'linear-gradient(135deg, #1B73B8 0%, #32A5DC 100%)', fontFamily:"Cabinet Grotesk"}}
          >
            D
          </div>
          <div className="leading-tight">
            <div className="font-bold text-sm tracking-tight text-slate-900" style={{fontFamily:"Cabinet Grotesk"}}>DACOT</div>
            <div className="text-[9px] text-slate-400 uppercase tracking-widest font-semibold">Hub</div>
          </div>
        </div>

        <div className="max-w-md w-full self-center py-10 lg:py-0">
          <div className="text-[11px] uppercase tracking-widest font-bold text-[var(--dh-accent)] mb-5">
            Painel Administrativo
          </div>
          <h1 className="text-5xl lg:text-[56px] font-bold tracking-tight text-slate-900 leading-[1.1] mb-4" style={{fontFamily:"Cabinet Grotesk"}}>
            Bem-vindo ao DACOT Hub
          </h1>
          <p className="text-[15px] text-slate-600 mb-8 leading-relaxed">
            Gerencie restaurantes clientes, módulos disponibilizados e usuários — tudo num só lugar.
          </p>

          <form onSubmit={submit} className="space-y-5" data-testid="login-form">
            <div>
              <label className="block text-[13px] font-semibold text-slate-700 mb-2">E-mail</label>
              <input
                type="email" required autoFocus
                value={email} onChange={(e) => setEmail(e.target.value)}
                className="dh-input" placeholder="voce@dacot.com"
                data-testid="login-email"
              />
            </div>
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-[13px] font-semibold text-slate-700">Senha</label>
                <Link to="/forgot-password" className="text-[13px] font-semibold text-[var(--dh-accent)] hover:text-[var(--dh-accent-hover)] transition-colors" data-testid="forgot-link">
                  Esqueci a senha
                </Link>
              </div>
              <input
                type="password" required
                value={password} onChange={(e) => setPassword(e.target.value)}
                className="dh-input" placeholder="••••••••"
                data-testid="login-password"
              />
            </div>

            {error && (
              <div className="dh-chip dh-chip-error" data-testid="login-error">
                {error}
              </div>
            )}

            <button type="submit" disabled={busy}
                    className="dh-btn dh-btn-primary w-full py-3 text-[14px] font-semibold"
                    data-testid="login-submit">
              {busy ? "Entrando…" : "Entrar no Hub"}
            </button>
          </form>
        </div>

        <div className="text-[12px] text-slate-400">
          © {new Date().getFullYear()} DACOT • Sistemas para restaurantes
        </div>
      </div>

      {/* Right */}
      <div className="hidden lg:flex relative overflow-hidden items-center justify-center">
        <img
          src="/image0.jpg"
          alt="DACOT Hub - Plataforma modular"
          className="absolute inset-0 w-full h-full object-cover"
        />
      </div>
    </div>
  );
}
