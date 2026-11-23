import { ReactNode, useEffect, useState } from "react";
import { STATUS_LABEL } from "./types";

export function Spinner({ text = "Lädt…" }: { text?: string }) {
  return <div className="muted center pad">{text}</div>;
}

export function ErrorBox({ error, onRetry }: { error: string | null; onRetry?: () => void }) {
  if (!error) return null;
  return (
    <div className="alert error" role="alert">
      {error} {onRetry && <button className="link" onClick={onRetry}>Erneut versuchen</button>}
    </div>
  );
}

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="modal-bg" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className={`modal ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="icon" onClick={onClose} aria-label="Schließen">✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small className="muted">{hint}</small>}
    </label>
  );
}

export function Badge({ kind, children }: { kind?: "ok" | "warn" | "bad" | "info" | "muted"; children: ReactNode }) {
  return <span className={`badge ${kind ?? "muted"}`}>{children}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  const kind = status === "approved" ? "ok" : status === "rejected" || status === "cancelled" ? "bad" : "warn";
  return <Badge kind={kind}>{STATUS_LABEL[status] ?? status}</Badge>;
}

export function Card({ title, actions, children }: { title?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="card">
      {(title || actions) && (
        <div className="card-head">{title && <h2>{title}</h2>}<div className="row">{actions}</div></div>
      )}
      {children}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="muted center pad">{children}</p>;
}

/** Button mit Ladezustand, verhindert Doppelklicks. */
export function Btn({ onClick, children, kind, disabled, type = "button" }: {
  onClick?: () => void | Promise<void>; children: ReactNode; kind?: "primary" | "danger" | "ghost";
  disabled?: boolean; type?: "button" | "submit";
}) {
  const [busy, setBusy] = useState(false);
  const run = async () => {
    if (!onClick || busy) return;
    setBusy(true);
    try { await onClick(); } finally { setBusy(false); }
  };
  return <button type={type} className={`btn ${kind ?? ""}`} disabled={disabled || busy} onClick={type === "submit" ? undefined : run}>{busy ? "…" : children}</button>;
}

// ---------- Installation als App ----------
let deferred: any = null;
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); deferred = e; window.dispatchEvent(new Event("install-ready")); });
window.addEventListener("appinstalled", () => { deferred = null; window.dispatchEvent(new Event("install-ready")); });

export const isStandalone = (): boolean =>
  window.matchMedia("(display-mode: standalone)").matches || (navigator as any).standalone === true;
const isIOS = (): boolean => /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

export function InstallButton() {
  const [, force] = useState(0);
  const [help, setHelp] = useState(false);
  useEffect(() => {
    const h = () => force((x) => x + 1);
    window.addEventListener("install-ready", h);
    return () => window.removeEventListener("install-ready", h);
  }, []);
  if (isStandalone()) return <p className="muted">Die App ist installiert.</p>;
  const click = async () => {
    if (deferred) { deferred.prompt(); await deferred.userChoice; deferred = null; force((x) => x + 1); }
    else setHelp(true);
  };
  return (
    <>
      <button className="btn primary" onClick={click}>App installieren</button>
      {help && (
        <div className="alert info">
          {isIOS()
            ? "iPhone/iPad: In Safari auf „Teilen“ tippen und „Zum Home-Bildschirm“ wählen."
            : "Öffnen Sie das Browser-Menü (⋮) und wählen Sie „App installieren“ bzw. „Zum Startbildschirm hinzufügen“. Unter Linux/Windows/macOS: Installations-Symbol in der Adressleiste (Chrome/Edge)."}
        </div>
      )}
    </>
  );
}
