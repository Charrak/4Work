import { useState } from "react";
import { Link } from "react-router-dom";
import { downloadJson, get, post } from "../api";
import { useAuth, useTheme, useToast } from "../context";
import { AvailabilityCard } from "./Availability";
import { Btn, Card, ErrorBox, Field, InstallButton } from "../ui";

function b64url(buf: ArrayBuffer | null): string {
  if (!buf) return "";
  return btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function keyBytes(b64: string) {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export function More() {
  const { can, logout } = useAuth();
  const manage = can("users.manage") || can("settings.manage") || can("admin.audit") || can("admin.backup") || can("roles.manage");
  const links = [
    { to: "/tausch", label: "🔁 Tausch & offene Schichten", show: can("shifts.view") },
    { to: "/chat", label: "💬 Team-Chat", show: can("chat.use") },
    { to: "/dokumente", label: "📄 Dokumente", show: can("documents.view") },
    { to: "/berichte", label: "📊 Berichte", show: can("reports.view") },
    { to: "/verwaltung", label: "⚙️ Verwaltung", show: manage },
    { to: "/profil", label: "👤 Profil & Einstellungen", show: true },
    { to: "/datenschutz", label: "🔒 Datenschutz", show: true },
  ];
  return (
    <>
      <h1>Mehr</h1>
      <Card>
        {links.filter((l) => l.show).map((l) => <div className="list-item" key={l.to}><Link to={l.to}>{l.label}</Link></div>)}
        <div className="list-item"><button className="link" onClick={logout}>Abmelden</button></div>
      </Card>
    </>
  );
}

export function Profile() {
  const { me, logout, refresh } = useAuth();
  const toast = useToast();
  const [theme, nextTheme] = useTheme();
  const [cur, setCur] = useState("");
  const [pw, setPw] = useState("");
  const [error, setError] = useState<string | null>(null);

  const changePw = async () => {
    setError(null);
    try { await post("/auth/change-password", { current_password: cur, new_password: pw }); setCur(""); setPw(""); toast("Passwort geändert"); refresh(); }
    catch (e) { setError((e as Error).message); }
  };

  const enablePush = async () => {
    try {
      if (!("serviceWorker" in navigator) || !("PushManager" in window)) return toast("Dieses Gerät/Browser unterstützt keine Push-Nachrichten.", "error");
      const { public_key } = await get<{ public_key: string | null }>("/push/public-key");
      if (!public_key) return toast("Push ist auf dem Server nicht eingerichtet (VAPID-Schlüssel fehlen).", "error");
      if ((await Notification.requestPermission()) !== "granted") return toast("Benachrichtigungen wurden nicht erlaubt.", "error");
      const reg = await navigator.serviceWorker.ready;
      const sub = (await reg.pushManager.getSubscription()) ?? (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(public_key) }));
      await post("/push/subscribe", { endpoint: sub.endpoint, p256dh: b64url(sub.getKey("p256dh")), auth: b64url(sub.getKey("auth")) });
      toast("Benachrichtigungen aktiviert");
    } catch (e) { toast((e as Error).message, "error"); }
  };

  return (
    <>
      <h1>Profil</h1>
      <Card title={me!.name}><p className="muted">{me!.email}</p></Card>
      <Card title="App & Darstellung">
        <div className="stack">
          <InstallButton />
          <div><Btn onClick={enablePush}>Benachrichtigungen aktivieren</Btn></div>
          <div><Btn onClick={nextTheme}>Darstellung: {theme === "auto" ? "automatisch" : theme === "light" ? "hell" : "dunkel"}</Btn></div>
        </div>
      </Card>
      <AvailabilityCard />
      <Card title="Passwort ändern">
        <div className="stack">
          <Field label="Aktuelles Passwort"><input type="password" value={cur} onChange={(e) => setCur(e.target.value)} autoComplete="current-password" /></Field>
          <Field label="Neues Passwort" hint="Mindestens 10 Zeichen mit Buchstaben und Ziffern"><input type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="new-password" /></Field>
          <ErrorBox error={error} />
          <Btn kind="primary" onClick={changePw}>Passwort ändern</Btn>
        </div>
      </Card>
      <Card title="Meine Daten (DSGVO)">
        <p className="muted small">Sie können eine Kopie aller über Sie gespeicherten Daten herunterladen.</p>
        <Btn onClick={() => downloadJson(`/users/${me!.id}/export`, "meine-daten.json").catch((e) => toast((e as Error).message, "error"))}>Daten herunterladen</Btn>
      </Card>
      <Btn kind="danger" onClick={logout}>Abmelden</Btn>
    </>
  );
}
