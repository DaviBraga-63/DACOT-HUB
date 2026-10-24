import { memo, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { Eye, EyeOff } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

const FLOATING_PATH_COUNT = 36;

function createFloatingPaths(position) {
  return Array.from({ length: FLOATING_PATH_COUNT }, (_, index) => ({
    id: index,
    d: `M-${380 - index * 5 * position} -${189 + index * 6}C-${
      380 - index * 5 * position
    } -${189 + index * 6} -${312 - index * 5 * position} ${216 - index * 6} ${
      152 - index * 5 * position
    } ${343 - index * 6}C${616 - index * 5 * position} ${470 - index * 6} ${
      684 - index * 5 * position
    } ${875 - index * 6} ${684 - index * 5 * position} ${875 - index * 6}`,
    width: 0.5 + index * 0.03,
    opacity: 0.08 + index * 0.0034,
    style: {
      "--dh-floating-duration": `${20 + ((index * 7 + (position === 1 ? 3 : 0)) % 10)}s`,
      "--dh-floating-delay": `-${(index * 1.37 + (position === 1 ? 4.5 : 0)).toFixed(2)}s`,
    },
  }));
}

const FLOATING_PATHS = {
  1: createFloatingPaths(1),
  "-1": createFloatingPaths(-1),
};

const FloatingPaths = memo(function FloatingPaths({ position }) {
  const paths = FLOATING_PATHS[position];

  return (
    <div className="pointer-events-none absolute inset-0">
      <svg
        aria-hidden="true"
        className="h-full w-full text-white"
        viewBox="0 0 696 316"
        fill="none"
      >
        {paths.map((path) => (
          <path
            key={path.id}
            d={path.d}
            fill="none"
            stroke="currentColor"
            strokeWidth={path.width}
            strokeOpacity={path.opacity}
            pathLength="1"
            className="dh-floating-path"
            style={path.style}
          />
        ))}
      </svg>
    </div>
  );
});

export default function Login() {
  const { login, error, setError } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError(null);
    const data = await login(email.trim(), password);
    setBusy(false);
    if (data) navigate(data.user_type === "restaurant" ? "/portal" : "/painel", { replace: true });
  };

  return (
    <div className="relative min-h-[100svh] overflow-x-hidden bg-[#090909]">
      <div className="dh-login-background absolute inset-0" aria-hidden="true">
        <FloatingPaths position={1} />
        <FloatingPaths position={-1} />
      </div>

      <main className="relative z-10 flex min-h-[100svh] items-center justify-center px-6 py-28 sm:px-10 sm:py-24 lg:px-16">
        <div className="max-w-md w-full py-10 lg:py-0">
          <div className="text-[11px] uppercase tracking-widest font-bold text-[var(--dh-accent)] mb-5">
            Painel Administrativo
          </div>
          <h1 className="text-5xl lg:text-[56px] font-bold tracking-tight text-white leading-[1.1] mb-4" style={{fontFamily:"Cabinet Grotesk"}}>
            Bem-vindo ao DACOT Hub
          </h1>
          <p className="text-[15px] text-slate-300 mb-8 leading-relaxed">
            Gerencie restaurantes clientes, módulos disponibilizados e usuários — tudo num só lugar.
          </p>

          <form onSubmit={submit} className="space-y-5" data-testid="login-form">
            <div>
              <label className="block text-[13px] font-semibold text-slate-200 mb-2">E-mail</label>
              <input
                type="email" required
                value={email} onChange={(e) => setEmail(e.target.value)}
                className="dh-input dh-login-input" placeholder="voce@dacot.com"
                data-testid="login-email"
              />
            </div>
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-[13px] font-semibold text-slate-200">Senha</label>
                <Link to="/forgot-password" className="notranslate text-[13px] font-semibold text-[var(--dh-accent)] hover:text-[var(--dh-accent-hover)] transition-colors" translate="no" data-testid="forgot-link">
                  <span className="notranslate" translate="no">Esqueci a senha</span>
                </Link>
              </div>
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setShowPassword((visible) => !visible)}
                  className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-[var(--dh-muted)] transition-colors hover:text-[var(--dh-accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--dh-accent)] focus-visible:ring-inset"
                  aria-label={showPassword ? "Ocultar senha" : "Mostrar senha"}
                  data-testid="toggle-password-visibility"
                >
                  {showPassword ? <Eye size={18} aria-hidden="true" /> : <EyeOff size={18} aria-hidden="true" />}
                </button>
                <input
                  type={showPassword ? "text" : "password"} required
                  value={password} onChange={(e) => setPassword(e.target.value)}
                  className="dh-input dh-login-input pr-10" placeholder="••••••••"
                  data-testid="login-password"
                />
              </div>
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
      </main>
    </div>
  );
}
