import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

export default function FreshEntry() {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return undefined;
    started.current = true;
    let mounted = true;

    const clearSessionAndEnter = async () => {
      await logout();
      if (mounted) navigate("/login", { replace: true });
    };

    clearSessionAndEnter();
    return () => { mounted = false; };
  }, [logout, navigate]);

  return (
    <div className="w-full h-screen flex items-center justify-center text-sm text-[var(--dh-muted)]">
      Preparando login…
    </div>
  );
}
