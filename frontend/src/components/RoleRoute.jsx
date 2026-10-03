import { Navigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

export function StaffRoute({ children }) {
  const { user } = useAuth();
  if (user?.user_type === "restaurant") return <Navigate to="/portal" replace />;
  return children;
}

export function RestaurantRoute({ children }) {
  const { user } = useAuth();
  if (user?.user_type === "staff") return <Navigate to="/painel" replace />;
  return children;
}
