import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "@/context/AuthContext";
import { ThemeProvider } from "@/context/ThemeContext";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import ProtectedRoute from "@/components/ProtectedRoute";
import { RestaurantRoute, StaffRoute } from "@/components/RoleRoute";
import AppLayout from "@/components/AppLayout";
import PortalLayout from "@/components/PortalLayout";
import Login from "@/pages/Login";
import ForgotPassword from "@/pages/ForgotPassword";
import ResetPassword from "@/pages/ResetPassword";
import Dashboard from "@/pages/Dashboard";
import FreshEntry from "@/pages/FreshEntry";
import Clientes from "@/pages/Clientes";
import ClienteNovo from "@/pages/ClienteNovo";
import ClienteDetalhes from "@/pages/ClienteDetalhes";
import Modulos from "@/pages/Modulos";
import ModuloPedidos from "@/pages/ModuloPedidos";
import Equipe from "@/pages/Equipe";
import Portal from "@/pages/Portal";
import PortalModulos from "@/pages/PortalModulos";

export default function App() {
  return (
    <ThemeProvider>
      <div className="App">
        <BrowserRouter>
          <AuthProvider>
          <TooltipProvider>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/forgot-password" element={<ForgotPassword />} />
            <Route path="/reset-password" element={<ResetPassword />} />
            <Route path="/" element={<FreshEntry />} />
            <Route element={<ProtectedRoute><StaffRoute><AppLayout /></StaffRoute></ProtectedRoute>}>
              <Route path="/painel" element={<Dashboard />} />
              <Route path="/clientes" element={<Clientes />} />
              <Route path="/clientes/novo" element={<ClienteNovo />} />
              <Route path="/clientes/:id" element={<ClienteDetalhes />} />
              <Route path="/modulos" element={<Modulos />} />
              <Route path="/modulos/orders" element={<ModuloPedidos />} />
              <Route path="/equipe" element={<Equipe />} />
            </Route>
            <Route element={<ProtectedRoute><RestaurantRoute><PortalLayout /></RestaurantRoute></ProtectedRoute>}>
              <Route path="/portal" element={<Portal />} />
              <Route path="/portal/modulos" element={<PortalModulos />} />
            </Route>
            <Route path="*" element={<Navigate to="/login" replace />} />
          </Routes>
          <Toaster position="top-right" />
          </TooltipProvider>
          </AuthProvider>
        </BrowserRouter>
      </div>
    </ThemeProvider>
  );
}
