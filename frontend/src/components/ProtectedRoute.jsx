import { Navigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

export default function ProtectedRoute({ children }) {
  const { user } = useAuth();
  if (user === null) {
    return (
      <div className="w-full h-screen flex items-center justify-center text-sm text-[var(--dh-muted)]">
        Carregando…
      </div>
    );
  }
  if (user === false) return <Navigate to="/login" replace />;
  return children;
}
