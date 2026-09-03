import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import type { ReactNode } from "react";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import NewResearch from "./pages/NewResearch";
import LiveResearch from "./pages/LiveResearch";
import RunDiff from "./pages/RunDiff";
import History from "./pages/History";
import Knowledge from "./pages/Knowledge";
import EntityDetail from "./pages/EntityDetail";
import Monitoring from "./pages/Monitoring";
import Scheduled from "./pages/Scheduled";
import Notifications from "./pages/Notifications";
import Login from "./pages/Login";
import { AuthProvider, useAuth } from "./auth/AuthContext";

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-400">
        Loading…
      </div>
    );
  }
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="new" element={<NewResearch />} />
          <Route path="research/:id" element={<LiveResearch />} />
          <Route path="research/:id/diff/:otherId" element={<RunDiff />} />
          <Route path="history" element={<History />} />
          <Route path="scheduled" element={<Scheduled />} />
          <Route path="knowledge" element={<Knowledge />} />
          <Route path="knowledge/entities/:id" element={<EntityDetail />} />
          <Route path="notifications" element={<Notifications />} />
          <Route path="monitoring" element={<Monitoring />} />
        </Route>
      </Routes>
    </AuthProvider>
  );
}
