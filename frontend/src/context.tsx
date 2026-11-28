import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { ApiError, clearQueue, flushQueue, get, post, setQueueUser } from "./api";
import { startLive, stopLive } from "./live";
import type { Me } from "./types";

// ---------- Hinweise (Toasts) ----------
type Kind = "ok" | "error" | "info";
interface ToastItem { id: number; msg: string; kind: Kind }
const ToastCtx = createContext<(msg: string, kind?: Kind) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const toast = useCallback((msg: string, kind: Kind = "ok") => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { id, msg, kind }]);
    window.setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), kind === "error" ? 7000 : 3500);
  }, []);
  return (
    <ToastCtx.Provider value={toast}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.msg}</div>)}
      </div>
    </ToastCtx.Provider>
  );
}

// ---------- Anmeldung ----------
interface AuthState {
  me: Me | null | undefined;      // undefined = lädt
  can: (perm: string) => boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}
const AuthCtx = createContext<AuthState>(null as unknown as AuthState);
export const useAuth = () => useContext(AuthCtx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const toast = useToast();

  const refresh = useCallback(async () => {
    try {
      setMe(await get<Me>("/auth/me"));
    } catch (e) {
      // offline: vorhandene Sitzung nicht verwerfen
      if (e instanceof ApiError && e.isOffline) { setMe((cur) => (cur === undefined ? null : cur)); return; }
      setMe(null);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    const h = () => setMe(null);
    window.addEventListener("session-expired", h);
    return () => window.removeEventListener("session-expired", h);
  }, []);

  // Echtzeit-Verbindung nur solange angemeldet
  useEffect(() => {
    if (me) startLive(); else stopLive();
    return () => stopLive();
  }, [me?.id]);

  // Gemerkte Offline-Aktionen senden, sobald das Netz wieder da ist
  useEffect(() => {
    setQueueUser(me ? me.id : null);
    if (!me) return;
    const uid = me.id;
    const run = () => flushQueue(uid).then((notes) => notes.forEach((n) => toast(n, n.startsWith("Gesendet") ? "ok" : "error")));
    run();
    window.addEventListener("online", run);
    return () => window.removeEventListener("online", run);
  }, [me?.id, toast]);

  const login = async (email: string, password: string) => { setMe(await post<Me>("/auth/login", { email, password })); };
  const logout = async () => {
    try { await post("/auth/logout"); } catch { /* egal */ }
    try { navigator.serviceWorker?.controller?.postMessage("clear-api-cache"); const keys = await caches.keys(); await Promise.all(keys.filter((k) => k.startsWith("api-")).map((k) => caches.delete(k))); } catch { /* egal */ }
    const dropped = clearQueue();
    if (dropped) toast(`${dropped} nicht gesendete Aktion(en) wurden beim Abmelden verworfen.`, "error");
    setMe(null);
  };
  const can = (perm: string) => !!me && me.permissions.includes(perm);

  return <AuthCtx.Provider value={{ me, can, login, logout, refresh }}>{children}</AuthCtx.Provider>;
}

// ---------- Theme ----------
export function useTheme(): [string, () => void] {
  const [theme, setTheme] = useState<string>(() => localStorage.getItem("theme") || "auto");
  useEffect(() => {
    if (theme === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);
  const next = () => setTheme((t) => (t === "auto" ? "light" : t === "light" ? "dark" : "auto"));
  return [theme, next];
}
