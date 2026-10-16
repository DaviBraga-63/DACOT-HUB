import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { Eye, EyeOff } from "lucide-react";
import { motion, useReducedMotion } from "framer-motion";
import { useAuth } from "@/context/AuthContext";

const FLOATING_PATHS = Array.from({ length: 36 }, (_, index) => {
  const offset = index * 9;
  const y = 80 + index * 15;
  const depth = 155 + (index % 6) * 26;
  return `M ${-380 + offset} ${y - 135} C ${-70 + offset} ${y - depth}, ${165 + offset} ${y + depth}, ${470 + offset} ${y} S ${835 + offset} ${y - depth}, ${1180 + offset} ${y + 118}`;
});

function FloatingPaths({ direction = 1 }) {
  const reduceMotion = useReducedMotion();

  return (
    <svg
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 h-full w-full text-[var(--dh-accent-light)]"
      viewBox="0 0 960 720"
      preserveAspectRatio="none"
    >
      <g transform={direction === -1 ? "rotate(180 480 360)" : undefined}>
        {FLOATING_PATHS.map((path, index) => (
          <motion.path
            key={`${direction}-${path}`}
            d={path}
            fill="none"
            stroke="currentColor"
            strokeWidth="1"
            initial={reduceMotion ? false : { opacity: 0, pathLength: 0.35 }}
            animate={reduceMotion
              ? { opacity: 0.2, pathLength: 1 }
              : {
                  opacity: [0.04, 0.27, 0.08],
                  pathLength: [0.2, 1, 0.42],
                  x: [0, direction * (18 + (index % 4) * 4), 0],
                }}
            transition={reduceMotion
              ? { duration: 0 }
              : {
                  duration: 13 + (index % 7) * 1.15,
                  delay: index * 0.12,
                  ease: "easeInOut",
                  repeat: Infinity,
                  repeatType: "mirror",
                }}
          />
        ))}
      </g>
    </svg>
  );
}

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
    <div className="min-h-screen grid grid-cols-1 lg:grid-cols-2 bg-[var(--dh-bg)]">
      {/* Decorative desktop panel */}
      <div className="hidden lg:flex dh-login-hero relative overflow-hidden" aria-hidden="true">
        <FloatingPaths direction={1} />
        <FloatingPaths direction={-1} />
      </div>

      {/* DACOT form */}
      <div className="flex flex-col px-6 sm:px-10 lg:px-16 py-8 sm:py-12 lg:py-10">
        <div className="flex items-center gap-3">
          <div 
            className="w-10 h-10 rounded-lg flex items-center justify-center text-white font-bold shadow-md"
            style={{background: 'var(--dh-accent-gradient)', fontFamily:"Cabinet Grotesk"}}
          >
            D
          </div>
          <div className="leading-tight">
            <div className="font-bold text-sm tracking-tight text-slate-900" style={{fontFamily:"Cabinet Grotesk"}}>DACOT</div>
          </div>
        </div>

        <main className="flex flex-1 items-center justify-center">
        <div className="max-w-md w-full py-10 lg:py-0">
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
                  {showPassword ? <EyeOff size={18} aria-hidden="true" /> : <Eye size={18} aria-hidden="true" />}
                </button>
                <input
                  type={showPassword ? "text" : "password"} required
                  value={password} onChange={(e) => setPassword(e.target.value)}
                  className="dh-input pr-10" placeholder="••••••••"
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
    </div>
  );
}
