import { ReactNode, useEffect, useState } from "react";
import { Navigate, NavLink, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { queueLength } from "./api";
import { AuthProvider, ToastProvider, useAuth, useTheme } from "./context";
import { useOnline } from "./hooks";
import { Spinner } from "./ui";
import { Login, ResetConfirm, ResetRequest } from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Schedule from "./pages/Schedule";
import AvailabilityManage from "./pages/Availability";
import Swaps from "./pages/Swaps";
import Leave from "./pages/Leave";
import Time from "./pages/Time";
import Chat from "./pages/Chat";
import Reports from "./pages/Reports";
import Admin from "./pages/Admin";
import Documents from "./pages/Documents";
import Personnel from "./pages/Personnel";
import Privacy from "./pages/Privacy";
import Autoplan from "./pages/Autoplan";
import Tasks from "./pages/Tasks";
import { More, Profile } from "./pages/Profile";

function OfflineBanner() {
  const online = useOnline();
  const [q, setQ] = useState(queueLength());
  useEffect(() => {
    const h = () => setQ(queueLength());
    window.addEventListener("queue-changed", h);
    return () => window.removeEventListener("queue-changed", h);
  }, []);
  if (online && q === 0) return null;
  return (
    <div className="offline-banner" role="status">
      {online
        ? `${q} Aktion(en) werden gesendet …`
        : `Keine Internetverbindung. Sie sehen den zuletzt geladenen Stand.${q ? ` ${q} Aktion(en) werden nach der Wiederverbindung gesendet.` : ""}`}
    </div>
  );
}

function Protected() {
  const { me } = useAuth();
  const loc = useLocation();
  if (me === undefined) return <Spinner text="Anmeldung wird geprüft…" />;
  if (me === null) return <Navigate to="/login" state={{ from: loc.pathname }} replace />;
  return <Layout />;
}

function Layout() {
  const { me, can } = useAuth();
  const [theme, nextTheme] = useTheme();
  const manage = can("users.manage") || can("settings.manage") || can("admin.audit") || can("admin.backup") || can("roles.manage");
  const items: { to: string; label: string; icon: string; show: boolean; mobile: boolean }[] = [
    { to: "/", label: "Start", icon: "🏠", show: true, mobile: true },
    { to: "/plan", label: "Dienstplan", icon: "📅", show: can("shifts.view"), mobile: true },
    { to: "/zeit", label: "Zeit", icon: "⏱️", show: can("time.clock") || can("time.approve"), mobile: true },
    { to: "/urlaub", label: "Urlaub", icon: "🌴", show: can("leave.request") || can("leave.approve"), mobile: true },
    { to: "/aufgaben", label: "Aufgaben", icon: "✅", show: can("tasks.do") || can("tasks.create") || can("tasks.manage"), mobile: true },
    { to: "/tausch", label: "Tausch", icon: "🔁", show: can("shifts.view"), mobile: false },
    { to: "/chat", label: "Chat", icon: "💬", show: can("chat.use"), mobile: false },
    { to: "/dokumente", label: "Dokumente", icon: "📄", show: can("documents.view"), mobile: false },
    { to: "/berichte", label: "Berichte", icon: "📊", show: can("reports.view"), mobile: false },
    { to: "/verwaltung", label: "Verwaltung", icon: "⚙️", show: manage, mobile: false },
  ];
  const visible = items.filter((i) => i.show);
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><img src="/logo.png" alt="physio & fit VitalZentrum Eschweiler" /></div>
        <nav>
          {visible.map((i) => (
            <NavLink key={i.to} to={i.to} end={i.to === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
              <span aria-hidden>{i.icon}</span> {i.label}
            </NavLink>
          ))}
          <NavLink to="/profil" className={({ isActive }) => (isActive ? "active" : "")}><span aria-hidden>👤</span> Profil</NavLink>
          <NavLink to="/datenschutz" className={({ isActive }) => (isActive ? "active" : "")}><span aria-hidden>🔒</span> Datenschutz</NavLink>
        </nav>
        <div className="side-foot">
          <div className="muted small">{me!.name}</div>
          <button className="link" onClick={nextTheme}>Darstellung: {theme === "auto" ? "automatisch" : theme === "light" ? "hell" : "dunkel"}</button>
        </div>
      </aside>
      <main className="content"><Outlet /></main>
      <nav className="tabbar" aria-label="Hauptnavigation">
        {visible.filter((i) => i.mobile).map((i) => (
          <NavLink key={i.to} to={i.to} end={i.to === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
            <span aria-hidden>{i.icon}</span><small>{i.label}</small>
          </NavLink>
        ))}
        <NavLink to="/mehr" className={({ isActive }) => (isActive ? "active" : "")}><span aria-hidden>☰</span><small>Mehr</small></NavLink>
      </nav>
    </div>
  );
}

function Guard({ perm, children }: { perm: string[]; children: ReactNode }) {
  const { can } = useAuth();
  return perm.some(can) ? <>{children}</> : <Navigate to="/" replace />;
}

export default function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <OfflineBanner />
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/passwort-vergessen" element={<ResetRequest />} />
          <Route path="/passwort-zuruecksetzen" element={<ResetConfirm />} />
          <Route element={<Protected />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/plan" element={<Guard perm={["shifts.view"]}><Schedule /></Guard>} />
            <Route path="/verfuegbarkeit" element={<Guard perm={["availability.manage"]}><AvailabilityManage /></Guard>} />
            <Route path="/autoplaner" element={<Guard perm={["shifts.manage"]}><Autoplan /></Guard>} />
            <Route path="/aufgaben" element={<Guard perm={["tasks.do", "tasks.create", "tasks.manage"]}><Tasks /></Guard>} />
            <Route path="/tausch" element={<Guard perm={["shifts.view"]}><Swaps /></Guard>} />
            <Route path="/urlaub" element={<Guard perm={["leave.request", "leave.approve"]}><Leave /></Guard>} />
            <Route path="/zeit" element={<Guard perm={["time.clock", "time.approve"]}><Time /></Guard>} />
            <Route path="/chat" element={<Guard perm={["chat.use"]}><Chat /></Guard>} />
            <Route path="/berichte" element={<Guard perm={["reports.view"]}><Reports /></Guard>} />
            <Route path="/verwaltung" element={<Guard perm={["users.manage", "settings.manage", "admin.audit", "admin.backup", "roles.manage"]}><Admin /></Guard>} />
            <Route path="/personal/:id" element={<Guard perm={["users.manage"]}><Personnel /></Guard>} />
            <Route path="/dokumente" element={<Guard perm={["documents.view", "documents.manage"]}><Documents /></Guard>} />
            <Route path="/datenschutz" element={<Privacy />} />
            <Route path="/mehr" element={<More />} />
            <Route path="/profil" element={<Profile />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </ToastProvider>
  );
}
