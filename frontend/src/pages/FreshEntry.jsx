import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

export default function FreshEntry() {
  const { beginFreshEntry } = useAuth();
  const navigate = useNavigate();
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return undefined;
    started.current = true;
    let mounted = true;

    // A new root entry must never revoke server sessions held by other tabs.
    beginFreshEntry();
    if (mounted) navigate("/login", { replace: true });
    return () => { mounted = false; };
  }, [beginFreshEntry, navigate]);

  return (
    <div className="w-full h-screen flex items-center justify-center text-sm text-[var(--dh-muted)]">
      Preparando login…
    </div>
  );
}
