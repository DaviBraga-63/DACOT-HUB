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
      <div className="flex flex-col justify-between px-10 lg:px-16 py-10">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 bg-[var(--dh-accent)] rounded-sm flex items-center justify-center text-white font-black" style={{fontFamily:"Cabinet Grotesk"}}>D</div>
          <div className="leading-tight">
            <div className="font-black text-[16px]" style={{fontFamily:"Cabinet Grotesk"}}>DACOT</div>
            <div className="text-[10px] text-[var(--dh-muted)] uppercase tracking-widest font-bold">Hub</div>
          </div>
        </div>

        <div className="max-w-md w-full self-center">
          <div className="text-[11px] uppercase tracking-widest font-bold text-[var(--dh-accent)] mb-4">
            Painel Administrativo
          </div>
          <h1 className="text-4xl lg:text-5xl font-black tracking-tight text-[var(--dh-text)] leading-[1.05] mb-3" style={{fontFamily:"Cabinet Grotesk"}}>
            Bem-vindo ao<br/>DACOT Hub.
          </h1>
          <p className="text-[15px] text-[var(--dh-muted)] mb-8 leading-relaxed">
            Gerencie restaurantes clientes, módulos disponibilizados e usuários — tudo num só lugar.
          </p>

          <form onSubmit={submit} className="space-y-4" data-testid="login-form">
            <div>
              <label className="block text-[11px] uppercase tracking-widest font-bold text-[var(--dh-muted)] mb-2">E-mail</label>
              <input
                type="email" required autoFocus
                value={email} onChange={(e) => setEmail(e.target.value)}
                className="dh-input" placeholder="voce@dacot.com"
                data-testid="login-email"
              />
            </div>
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-[11px] uppercase tracking-widest font-bold text-[var(--dh-muted)]">Senha</label>
                <Link to="/forgot-password" className="text-[11px] uppercase tracking-widest font-bold text-[var(--dh-accent)] hover:text-[var(--dh-accent-hover)]" data-testid="forgot-link">
                  Esqueci
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
                    className="dh-btn dh-btn-primary w-full py-3 text-[13px] uppercase tracking-widest"
                    data-testid="login-submit">
              {busy ? "Entrando…" : "Entrar no Hub"}
            </button>
          </form>
        </div>

        <div className="text-[11px] text-[var(--dh-muted)]">
          © {new Date().getFullYear()} DACOT • Sistemas para restaurantes
        </div>
      </div>

      {/* Right */}
      <div className="hidden lg:block relative overflow-hidden border-l border-[var(--dh-border)]">
        <img
          src="https://images.unsplash.com/photo-1454117096348-e4abbeba002c?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NTYxOTF8MHwxfHNlYXJjaHwzfHxtaW5pbWFsaXN0JTIwYWJzdHJhY3QlMjBnZW9tZXRyaWMlMjB0ZXh0dXJlfGVufDB8fHx8MTc4NzkxNDMxOXww&ixlib=rb-4.1.0&q=85"
          alt="" className="absolute inset-0 w-full h-full object-cover"
        />
        <div className="absolute inset-0 bg-[#1A1D1A]/40" />
        <div className="absolute bottom-10 left-10 right-10 text-white">
          <div className="text-[11px] uppercase tracking-widest font-bold mb-3 opacity-80">Plataforma modular</div>
          <div className="text-3xl font-black leading-tight max-w-md" style={{fontFamily:"Cabinet Grotesk"}}>
            Um ecossistema completo para operações gastronômicas.
          </div>
        </div>
      </div>
    </div>
  );
}
